"""
数据加载器模块：自动解压并加载 CSV/Excel/JSON 格式的企业数据，支持批量导入和 API 实时数据接入
"""

import csv
import json
import os
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from mining_risk_common.utils.config import get_config, resolve_project_path
from mining_risk_common.utils.exceptions import DataLoadingError
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


class DataUploadRequest(BaseModel):
    """数据上传请求模型"""
    enterprise_id: str
    data_format: str = Field(default="csv", pattern="^(csv|excel|json)$")
    content: Union[str, bytes, Dict]
    timestamp: Optional[str] = None

    @field_validator("data_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = {"csv", "excel", "json"}
        if v not in allowed:
            raise ValueError(f"不支持的格式: {v}，仅支持 {allowed}")
        return v


class DataLoader:
    """
    企业数据加载器
    
    功能：
    1. 自动解压 ZIP 数据包
    2. 批量加载 CSV/Excel/JSON 文件
    3. 支持通过 API 上传单条/批量数据
    4. 自动识别编码并统一转换为 DataFrame
    """

    def __init__(self, raw_data_path: Optional[str] = None):
        config = get_config()
        self.raw_data_path = str(
            self._resolve_existing_path(raw_data_path)
            if raw_data_path is not None
            else self._resolve_path(config.data.raw_data_path)
        )
        self.reference_data_path = str(self._resolve_path(config.data.reference_data_path))
        self.merged_data_path = (
            str(self._resolve_path(config.data.merged_data_path))
            if config.data.merged_data_path
            else None
        )
        self.public_data_root = (
            str(self._resolve_path(config.data.public_data_root))
            if config.data.public_data_root
            else None
        )
        self.all_public_data_paths = [
            str(self._resolve_path(path))
            for path in (config.data.all_public_data_paths or [])
        ]
        self.encoding = config.data.encoding
        self.supported_formats = config.data.supported_formats
        self.supported_suffixes = self._supported_suffixes(self.supported_formats)
        self.csv_encoding_fallbacks = self._unique_encodings(
            [self.encoding, *config.data.csv_encoding_fallbacks, "utf-8", "gb18030", "gbk"]
        )
        self._cache: Dict[str, pd.DataFrame] = {}

    @staticmethod
    def _resolve_path(path: Union[str, Path]) -> Path:
        """Resolve configured relative paths from the project root."""
        return resolve_project_path(path)

    @staticmethod
    def _resolve_existing_path(path: Union[str, Path]) -> Path:
        path_obj = Path(path)
        if path_obj.exists() or path_obj.is_absolute():
            return path_obj.resolve()
        return resolve_project_path(path_obj)

    @staticmethod
    def _supported_suffixes(formats: Sequence[str]) -> set[str]:
        suffixes: set[str] = set()
        for fmt in formats:
            normalized = fmt.lower().lstrip(".")
            if normalized == "excel":
                suffixes.update({".xlsx", ".xls"})
            elif normalized in {"csv", "xlsx", "xls", "json"}:
                suffixes.add(f".{normalized}")
        return suffixes

    @staticmethod
    def _unique_encodings(encodings: Sequence[str]) -> List[str]:
        unique: List[str] = []
        for encoding in encodings:
            if encoding and encoding not in unique:
                unique.append(encoding)
        return unique

    @staticmethod
    def _clean_column_name(column: object, index: int) -> str:
        name = "" if column is None else str(column)
        name = name.replace("\ufeff", "").strip()
        return name or f"Unnamed: {index}"

    def _deduplicate_columns(self, columns: Sequence[object], source: str = "") -> List[str]:
        counts: Dict[str, int] = {}
        deduplicated: List[str] = []
        renamed: List[str] = []

        for index, column in enumerate(columns):
            base_name = self._clean_column_name(column, index)
            count = counts.get(base_name, 0) + 1
            counts[base_name] = count

            if count == 1:
                deduplicated.append(base_name)
                continue

            new_name = f"{base_name}__dup{count}"
            deduplicated.append(new_name)
            renamed.append(f"{base_name} -> {new_name}")

        if renamed:
            location = f" in {source}" if source else ""
            logger.warning("重复字段已追加 __dupN 后缀%s: %s", location, "; ".join(renamed))

        return deduplicated

    def _read_csv_header(self, file_path: Path, encoding: str, kwargs: Dict) -> Optional[List[str]]:
        header = kwargs.get("header", "infer")
        if kwargs.get("names") is not None or header not in ("infer", 0):
            return None

        delimiter = kwargs.get("delimiter", kwargs.get("sep", ","))
        if delimiter is None:
            delimiter = ","
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            return None

        with file_path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            try:
                return next(reader)
            except StopIteration:
                return []

    def _read_csv_with_fallback(self, file_path: Path, **kwargs) -> pd.DataFrame:
        read_kwargs = dict(kwargs)
        requested_encoding = read_kwargs.pop("encoding", None) or self.encoding
        encodings = self._unique_encodings(
            [requested_encoding, *self.csv_encoding_fallbacks]
        )
        last_error: Optional[Exception] = None

        for encoding in encodings:
            try:
                csv_kwargs = dict(read_kwargs)
                raw_columns = self._read_csv_header(file_path, encoding, csv_kwargs)
                if raw_columns is not None:
                    csv_kwargs["header"] = 0
                    csv_kwargs["names"] = self._deduplicate_columns(raw_columns, str(file_path))

                df = pd.read_csv(file_path, encoding=encoding, **csv_kwargs)
                if raw_columns is None:
                    df.columns = self._deduplicate_columns(list(df.columns), str(file_path))

                if encoding != requested_encoding:
                    logger.warning(
                        "CSV 文件 %s 使用备用编码 %s 读取（首选编码 %s 失败）",
                        file_path,
                        encoding,
                        requested_encoding,
                    )
                return df
            except (UnicodeDecodeError, pd.errors.ParserError, LookupError) as exc:
                last_error = exc
                continue
            except Exception as exc:
                last_error = exc
                break

        raise DataLoadingError(f"CSV 文件无法读取 {file_path}: {last_error}")

    @staticmethod
    def _drop_unsupported_kwargs(ext: str, kwargs: Dict) -> Dict:
        cleaned = dict(kwargs)
        if ext in {".xlsx", ".xls", ".json"}:
            cleaned.pop("low_memory", None)
        return cleaned

    def _iter_data_files(self, directory: Path, pattern: str = "*") -> List[Path]:
        return sorted(
            path
            for path in directory.rglob(pattern)
            if path.is_file() and path.suffix.lower() in self.supported_suffixes
        )

    @staticmethod
    def _result_key(file_path: Path, root: Path, existing: Dict[str, pd.DataFrame]) -> str:
        try:
            key = file_path.relative_to(root).with_suffix("").as_posix()
        except ValueError:
            key = file_path.stem

        if key not in existing:
            return key

        index = 2
        while f"{key}__{index}" in existing:
            index += 1
        return f"{key}__{index}"

    def auto_unzip(self, zip_path: str, extract_to: Optional[str] = None) -> str:
        """
        自动解压 ZIP 数据?        
        Args:
            zip_path: ZIP 文件路径
            extract_to: 解压目标目录，默认为 ZIP 同级目录
        
        Returns:
            解压后的目录路径
        """
        if not os.path.exists(zip_path):
            raise DataLoadingError(f"ZIP 文件不存在: {zip_path}")
        
        if extract_to is None:
            extract_to = os.path.splitext(zip_path)[0]
        
        os.makedirs(extract_to, exist_ok=True)
        
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_to)
            logger.info(f"成功解压 {zip_path} 到 {extract_to}")
            return extract_to
        except zipfile.BadZipFile as e:
            raise DataLoadingError(f"ZIP 文件损坏: {e}")
        except Exception as e:
            raise DataLoadingError(f"解压失败: {e}")

    def load_file(self, file_path: Union[str, Path], **kwargs) -> pd.DataFrame:
        """
        加载单个数据文件
        
        Args:
            file_path: 文件路径
            **kwargs: 额外的 pandas 读取参数
        
        Returns:
            DataFrame
        """
        resolved_path = self._resolve_existing_path(file_path)
        if not resolved_path.exists():
            raise DataLoadingError(f"文件不存在: {resolved_path}")

        ext = resolved_path.suffix.lower()
        read_kwargs = self._drop_unsupported_kwargs(ext, kwargs)
        
        try:
            if ext == ".csv":
                df = self._read_csv_with_fallback(resolved_path, **read_kwargs)
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(resolved_path, **read_kwargs)
                df.columns = self._deduplicate_columns(list(df.columns), str(resolved_path))
            elif ext == ".json":
                df = pd.read_json(resolved_path, **read_kwargs)
                if hasattr(df, "columns"):
                    df.columns = self._deduplicate_columns(list(df.columns), str(resolved_path))
            else:
                raise DataLoadingError(f"不支持的文件格式: {ext}")
            
            logger.info(f"成功加载 {resolved_path}，形状: {df.shape}")
            return df
        except DataLoadingError:
            raise
        except Exception as e:
            if ext in (".xlsx", ".xls"):
                raise DataLoadingError(
                    f"Excel 文件无法读取，可能文件头损坏或格式与扩展名不匹配: {resolved_path}: {e}"
                )
            raise DataLoadingError(f"加载文件失败 {resolved_path}: {e}")

    def load_directory(
        self,
        directory: Optional[Union[str, Path]] = None,
        pattern: str = "*",
        skip_errors: bool = True,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        """
        批量加载目录下的所有支持格式文件
        
        Args:
            directory: 目标目录，默认使用配置中的 raw_data_path
            pattern: 文件匹配模式
        
        Returns:
            文件名 -> DataFrame 的字典
        """
        directory_path = self._resolve_existing_path(directory or self.raw_data_path)
        if not directory_path.exists():
            raise DataLoadingError(f"目录不存在: {directory_path}")
        
        results: Dict[str, pd.DataFrame] = {}

        for file_path in self._iter_data_files(directory_path, pattern):
            key = self._result_key(file_path, directory_path, results)
            try:
                results[key] = self.load_file(file_path, **kwargs)
            except DataLoadingError as e:
                if not skip_errors:
                    raise
                logger.warning("跳过无法读取的数据文件 %s: %s", file_path, e)
        
        logger.info(f"目录 {directory_path} 共加载 {len(results)} 个文件")
        return results

    def load_public_data(
        self,
        paths: Optional[Sequence[Union[str, Path]]] = None,
        pattern: str = "*",
        skip_errors: bool = True,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        """递归加载公开数据根目录下所有受支持的 CSV/XLSX/JSON 文件。"""
        if paths is None:
            target_paths = list(self.all_public_data_paths)
        elif isinstance(paths, (str, Path)):
            target_paths = [paths]
        else:
            target_paths = list(paths)
        if not target_paths and self.public_data_root:
            target_paths = [self.public_data_root]
        if not target_paths:
            raise DataLoadingError("未配置 public_data_root 或 all_public_data_paths")

        results: Dict[str, pd.DataFrame] = {}
        for target in target_paths:
            directory_path = self._resolve_existing_path(target)
            if not directory_path.exists():
                raise DataLoadingError(f"公开数据目录不存在: {directory_path}")

            for file_path in self._iter_data_files(directory_path, pattern):
                key = self._result_key(file_path, directory_path, results)
                try:
                    results[key] = self.load_file(file_path, **kwargs)
                except DataLoadingError as e:
                    if not skip_errors:
                        raise
                    logger.warning("跳过无法读取的数据文件 %s: %s", file_path, e)

        logger.info(f"公开数据扫描共加载 {len(results)} 个文件")
        return results

    def load_from_api(self, request: DataUploadRequest) -> pd.DataFrame:
        """
        从 API 请求加载数据
        
        Args:
            request: 数据上传请求对象
        
        Returns:
            DataFrame
        """
        fmt = request.data_format
        content = request.content
        
        try:
            if fmt == "csv":
                if isinstance(content, str):
                    from io import StringIO
                    df = pd.read_csv(StringIO(content), encoding=self.encoding)
                else:
                    from io import BytesIO
                    df = pd.read_csv(BytesIO(content), encoding=self.encoding)
            elif fmt == "excel":
                from io import BytesIO
                if isinstance(content, str):
                    content = content.encode(self.encoding)
                df = pd.read_excel(BytesIO(content))
            elif fmt == "json":
                if isinstance(content, dict):
                    df = pd.json_normalize(content)
                else:
                    from io import StringIO
                    df = pd.read_json(StringIO(content))
            else:
                raise DataLoadingError(f"不支持的格式: {fmt}")

            if hasattr(df, "columns"):
                df.columns = self._deduplicate_columns(list(df.columns), f"API {fmt}")
            
            logger.info(f"API 数据加载成功，企业ID: {request.enterprise_id}, 形状: {df.shape}")
            return df
        except Exception as e:
            raise DataLoadingError(f"API 数据加载失败: {e}")

    def load_merged_dataset(self, **kwargs) -> pd.DataFrame:
        """
        加载预合并训练集 new_已清洗.xlsx（80016行×214列）

        该文件是对数据补充目录各表的跨系统整合结果，直接用于模型训练。
        各原始表之间 ID 体系不兼容（详见 results.md §10.2），无法在代码层 join。

        Returns:
            完整训练 DataFrame，含目标列 new_level（A/B/C/D）
        """
        merged_path = self.merged_data_path
        if not merged_path:
            raise DataLoadingError("config.data.merged_data_path 未配置")

        logger.info(f"加载预合并训练集: {merged_path}")
        return self.load_file(merged_path, **kwargs)

    def merge_enterprise_tables(
        self,
        tables: Dict[str, pd.DataFrame],
        join_keys: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        合并企业多表数据

        实际 join 路径（基于数据集 ID 体系）：
          enterprise_information.报告历史id
              → enterprise_risk_history.主键ID
              → enterprise_risk.报告历史ID
              → enterprise_safety.报告历史ID
          enterprise_information.统一社会信用代码
              → enterprise_dust_clear_record.统一信用代码
              → st_enterprise_directory.社会统一信用代码 主键

        注意：数据补充目录中各表 500 行样本 ID 互不重叠，
        仅完整数据集可做有效 join。推荐直接使用 load_merged_dataset()。

        Args:
            tables: 表名 -> DataFrame 字典，key 应与表文件名 stem 对应
            join_keys: 覆盖默认 join 键顺序

        Returns:
            合并后的 DataFrame
        """
        if not tables:
            raise DataLoadingError("输入表字典为空")

        # 按实际 ID 体系定义每张表的主键和外键
        TABLE_KEYS: Dict[str, Dict[str, str]] = {
            "szs_enterprise_information": {
                "primary": "主键ID",
                "report_fk": "报告历史id",
                "credit_fk": "统一社会信用代码",
            },
            "szs_enterprise_risk_history": {
                "primary": "主键ID",  # = enterprise_information.报告历史id
                "enterprise_fk": "企业ID",
            },
            "szs_enterprise_risk": {
                "primary": "主键ID",
                "report_fk": "报告历史ID",  # → risk_history.主键ID
            },
            "szs_enterprise_safety": {
                "primary": "主键ID",
                "report_fk": "报告历史ID",  # → risk_history.主键ID
            },
            "st_enterprise_directory": {
                "primary": "社会统一信用代码 主键",
            },
            "szs_enterprise_dust_clear_record": {
                "primary": "主键id",
                "credit_fk": "统一信用代码",  # → enterprise_information.统一社会信用代码
            },
        }

        # 若调用方传入了覆盖键，沿用旧逻辑（单键 outer join）
        if join_keys is not None:
            first_df = list(tables.values())[0]
            actual_key = next((k for k in join_keys if k in first_df.columns), None)
            if actual_key is None:
                raise DataLoadingError(f"未找到可用的关联主键: {join_keys}")
            merged = None
            for name, df in tables.items():
                if actual_key not in df.columns:
                    logger.warning(f"表 {name} 缺少关联键 {actual_key}，跳过")
                    continue
                if merged is None:
                    merged = df.copy()
                else:
                    overlap = [c for c in df.columns if c in merged.columns and c != actual_key]
                    df_r = df.rename(columns={c: f"{name}_{c}" for c in overlap})
                    merged = pd.merge(merged, df_r, on=actual_key, how="outer")
            if merged is None:
                raise DataLoadingError("所有表均缺少指定关联键，合并失败")
            logger.info(f"多表合并完成（覆盖键模式），关联键: {actual_key}, 形状: {merged.shape}")
            return merged

        # 以 enterprise_information 为基表，按层级 join
        base_name = next(
            (k for k in tables if "information" in k.lower()),
            next(iter(tables)),
        )
        merged = tables[base_name].copy()
        info_keys = TABLE_KEYS.get(base_name, {})
        report_key_left = info_keys.get("report_fk") or info_keys.get("primary", "主键ID")
        credit_key_left = info_keys.get("credit_fk", "统一社会信用代码")

        for name, df in tables.items():
            if name == base_name:
                continue
            tkeys = TABLE_KEYS.get(name, {})

            # 确定 join 键对
            right_report_fk = tkeys.get("report_fk") or tkeys.get("primary")
            right_credit_fk = tkeys.get("credit_fk")

            if right_report_fk and report_key_left in merged.columns and right_report_fk in df.columns:
                left_on, right_on = report_key_left, right_report_fk
            elif right_credit_fk and credit_key_left in merged.columns and right_credit_fk in df.columns:
                left_on, right_on = credit_key_left, right_credit_fk
            else:
                logger.warning(f"表 {name} 无法确定 join 键，跳过")
                continue

            overlap = [c for c in df.columns if c in merged.columns and c not in (left_on, right_on)]
            df_r = df.rename(columns={c: f"{name}_{c}" for c in overlap})
            merged = pd.merge(merged, df_r, left_on=left_on, right_on=right_on, how="left")
            logger.info(f"已 join 表 {name}（{left_on} → {right_on}），当前形状: {merged.shape}")

        logger.info(f"多表合并完成，最终形状: {merged.shape}")
        return merged

    def get_cached(self, key: str) -> Optional[pd.DataFrame]:
        """获取缓存的数据"""
        return self._cache.get(key)

    def set_cache(self, key: str, df: pd.DataFrame) -> None:
        """设置缓存"""
        self._cache[key] = df
