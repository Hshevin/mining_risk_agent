"""
特征工程与数据预处理模块
严格对齐《建设方案》0.1 节要求
覆盖特征汇总表全部字段的特殊逻辑：
  - 干湿除尘比例
  - 有限空间 OR 逻辑
  - 危化品 OR 逻辑
  - 时间衰减加权
  - 地理围栏
  - 按企业聚合（隐患/文书加权）
  - 数据可信度系数
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from utils.config import get_config
from utils.exceptions import FeatureEngineeringError
from utils.logger import get_logger

logger = get_logger(__name__)


class BinaryEncoder(BaseEstimator, TransformerMixin):
    """
    二值型编码器
    将"是"/"True/False"等多格式取值统一映射为 0/1
    固定风险方向：1=存在风险/高风险状态，0=无风险/低风险状态
    """

    def __init__(self):
        self.positive_values = {"是", "有", "true", "1", "yes", "y", "t", "存在", "有效", "落实"}
        self.negative_values = {"否", "无", "false", "0", "no", "n", "f", "不存在", "无效", "未落实"}

    def fit(self, X: pd.DataFrame, y=None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = X.copy()
        for col in result.columns:
            result[col] = result[col].apply(self._encode_value)
        return result

    def _encode_value(self, val: Any) -> int:
        if pd.isna(val):
            return 0  # 缺失默认为低风险
        s = str(val).strip().lower()
        if s in self.positive_values or s.startswith("1"):
            return 1
        if s in self.negative_values or s.startswith("0"):
            return 0
        # 尝试数值转换
        try:
            return 1 if float(s) > 0 else 0
        except ValueError:
            return 0


class NumericTransformer(BaseEstimator, TransformerMixin):
    """
    数值型变换器
    对数变换 + Min-Max 归一化
    支持分级加权求和
    """

    def __init__(self, clip_quantile: float = 0.99, use_log: bool = True):
        self.clip_quantile = clip_quantile
        self.use_log = use_log
        self.scaler = MinMaxScaler()
        self.upper_bounds_: Dict[str, float] = {}

    def fit(self, X: pd.DataFrame, y=None):
        for col in X.columns:
            upper = X[col].quantile(self.clip_quantile)
            self.upper_bounds_[col] = upper
        # 拟合 scaler（使用截断后的数据）
        X_clipped = self._clip_and_transform(X, fit=True)
        self.scaler.fit(X_clipped)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X_clipped = self._clip_and_transform(X, fit=False)
        scaled = self.scaler.transform(X_clipped)
        return pd.DataFrame(scaled, columns=X.columns, index=X.index)

    def _clip_and_transform(self, X: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        result = X.copy().astype(float)
        for col in result.columns:
            if col in self.upper_bounds_:
                result[col] = result[col].clip(upper=self.upper_bounds_[col])
            # 填充缺失
            mean_val = result[col].mean()
            result[col] = result[col].fillna(mean_val)
            # 对数变换（处理正值）
            if self.use_log:
                result[col] = np.log1p(np.maximum(result[col], 0))
        return result


class EnumRiskMapper(BaseEstimator, TransformerMixin):
    """
    枚举型风险映射器
    将枚举类别映射为风险程度数值
    """

    def __init__(self, risk_order: Optional[Dict[str, Dict[str, int]]] = None):
        self.risk_order = risk_order

    def fit(self, X: pd.DataFrame, y=None):
        self.fallback_mapping_: Dict[str, Dict[Any, int]] = {}
        for col in X.columns:
            unique_vals = X[col].dropna().unique()
            # 自动推断风险顺序（按字符串长度或数值大小排序）
            mapping = {}
            sorted_vals = sorted(unique_vals, key=lambda x: str(x))
            n = len(sorted_vals)
            for i, val in enumerate(sorted_vals):
                # 映射到 0-1 区间，越往后风险越高
                mapping[val] = i / max(n - 1, 1)
            self.fallback_mapping_[col] = mapping
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = X.copy()
        risk_order = self.risk_order or {}
        for col in result.columns:
            mapping = risk_order.get(col, self.fallback_mapping_.get(col, {}))
            result[col] = result[col].map(mapping).fillna(0.5)
        return result


class TextRiskExtractor(BaseEstimator, TransformerMixin):
    """
    文本型风险提取器
    1. 文本完整性评估（越短/NaN -> 高分 1.0），有内容 -> 低分
    2. 高危词匹配统计
    """

    HIGH_RISK_WORDS = [
        "爆炸", "火灾", "泄漏", "中毒", "坍塌", "瓦斯", "超限", "违规",
        "停产", "重大隐患", "死亡", "重伤", " pollution", "pollution",
        "爆裂", "窒息", "冒顶", "透水", "尾矿库", "溃坝", "重大危险源",
    ]

    def __init__(self, high_risk_words: Optional[List[str]] = None):
        self.high_risk_words = high_risk_words or self.HIGH_RISK_WORDS

    def fit(self, X: pd.DataFrame, y=None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        for col in X.columns:
            result[f"{col}_completeness"] = X[col].apply(self._completeness_score)
            result[f"{col}_risk_words"] = X[col].apply(self._count_risk_words)
        # 归一化
        for col in result.columns:
            max_val = result[col].max()
            if max_val > 0:
                result[col] = result[col] / max_val
        return result

    def _completeness_score(self, text: Any) -> float:
        """文本完整性评分：越短/NaN -> 高分（1.0），有内容 -> 低分"""
        if pd.isna(text):
            return 1.0
        s = str(text).strip()
        if s in {"", "无", "暂无", "null", "NULL", "NaN"}:
            return 1.0
        # 内容越详细，评分越低（风险越低）
        length = len(s)
        return max(0.0, 1.0 - length / 500.0)

    def _count_risk_words(self, text: Any) -> int:
        """统计高危词命中次数"""
        if pd.isna(text):
            return 0
        s = str(text)
        count = 0
        for word in self.high_risk_words:
            count += len(re.findall(word, s))
        return count


class IndustryRiskCoefficient(BaseEstimator, TransformerMixin):
    """
    行业风险系数映射器
    按行业风险基准表映射系数
    """

    DEFAULT_COEFFICIENTS = {
        "采矿": 1.5,
        "煤炭": 1.5,
        "金属": 1.4,
        "非金属矿": 1.3,
        "危险化学品": 1.5,
        "化工": 1.4,
        "石油": 1.4,
        "天然气": 1.4,
        "金属冶炼": 1.4,
        "钢铁": 1.3,
        "有色金属": 1.3,
        "制造业": 1.0,
        "建筑": 1.1,
        "default": 1.0,
    }

    def __init__(self, coefficients: Optional[Dict[str, float]] = None):
        self.coefficients = coefficients or self.DEFAULT_COEFFICIENTS

    def fit(self, X: pd.DataFrame, y=None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        # 取第一个行业列作为基准
        if len(X.columns) == 0:
            return result
        
        base_col = X.columns[0]
        result["industry_risk_coefficient"] = X[base_col].apply(self._map_coefficient)
        return result

    def _map_coefficient(self, val: Any) -> float:
        if pd.isna(val):
            return self.coefficients["default"]
        s = str(val)
        for key, coef in self.coefficients.items():
            if key in s:
                return coef
        return self.coefficients["default"]


class MissingValueHandler(BaseEstimator, TransformerMixin):
    """
    缺失值处理器
    - 管理类字段缺失：赋中/高分
    - 客观统计值缺失：填充全局/行业均值
    """

    def __init__(
        self,
        management_fields: Optional[List[str]] = None,
        objective_fields: Optional[List[str]] = None,
        management_score: float = 0.7,
    ):
        self.management_fields = management_fields or []
        self.objective_fields = objective_fields or []
        self.management_score = management_score
        self.means_: Dict[str, float] = {}

    def fit(self, X: pd.DataFrame, y=None):
        for col in self.objective_fields:
            if col in X.columns:
                self.means_[col] = X[col].mean()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = X.copy()
        for col in self.management_fields:
            if col in result.columns:
                result[col] = result[col].fillna(self.management_score)
        for col in self.objective_fields:
            if col in result.columns:
                result[col] = result[col].fillna(self.means_.get(col, 0))
        return result


class DustRemovalRatioTransformer(BaseEstimator, TransformerMixin):
    """
    干湿除尘比例特征生成器
    基于除尘记录表计算干式/湿式除尘比例
    """

    def __init__(
        self,
        dry_col: Optional[str] = None,
        wet_col: Optional[str] = None,
        total_col: Optional[str] = None,
    ):
        self.dry_col = dry_col
        self.wet_col = wet_col
        self.total_col = total_col

    def fit(self, X: pd.DataFrame, y=None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        # 自动探测列名
        dry = self.dry_col or self._find_col(X, ["干式除尘", "干除尘", "dry_dust"])
        wet = self.wet_col or self._find_col(X, ["湿式除尘", "湿除尘", "wet_dust"])
        total = self.total_col or self._find_col(X, ["除尘次数", "除尘总数", "dust_total"])

        if dry and dry in X.columns:
            dry_val = pd.to_numeric(X[dry], errors="coerce").fillna(0)
        else:
            dry_val = pd.Series(0, index=X.index)

        if wet and wet in X.columns:
            wet_val = pd.to_numeric(X[wet], errors="coerce").fillna(0)
        else:
            wet_val = pd.Series(0, index=X.index)

        if total and total in X.columns:
            total_val = pd.to_numeric(X[total], errors="coerce").fillna(0)
        else:
            total_val = dry_val + wet_val

        total_val = total_val.replace(0, np.nan)
        result["dry_removal_ratio"] = (dry_val / total_val).fillna(0)
        result["wet_removal_ratio"] = (wet_val / total_val).fillna(0)
        return result

    def _find_col(self, X: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        for c in X.columns:
            for pat in candidates:
                if pat in c:
                    return c
        return None


class ConfinedSpaceORTransformer(BaseEstimator, TransformerMixin):
    """
    有限空间 OR 逻辑生成器
    三字段（或更多）取 OR：任一字段为真(1/是)则输出 1
    """

    def __init__(self, cols: Optional[List[str]] = None):
        self.cols = cols

    def fit(self, X: pd.DataFrame, y=None):
        if self.cols is None:
            self.cols = self._auto_detect(X)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if not self.cols:
            result["confined_space_flag"] = 0
            return result

        or_val = pd.Series(0, index=X.index)
        for col in self.cols:
            if col in X.columns:
                val = X[col].apply(self._to_binary)
                or_val = or_val | val
        result["confined_space_flag"] = or_val.astype(int)
        return result

    def _auto_detect(self, X: pd.DataFrame) -> List[str]:
        patterns = ["有限空间", "密闭空间", "受限空间", "confined_space", "空间作业"]
        found = []
        for c in X.columns:
            for p in patterns:
                if p in c:
                    found.append(c)
                    break
        return found

    def _to_binary(self, val: Any) -> int:
        if pd.isna(val):
            return 0
        s = str(val).strip().lower()
        if s in {"1", "是", "有", "true", "yes"}:
            return 1
        try:
            return 1 if float(s) > 0 else 0
        except ValueError:
            return 0


class HazardousChemicalORTransformer(BaseEstimator, TransformerMixin):
    """
    危化品 OR 逻辑生成器
    多个危化品相关字段取 OR
    """

    def __init__(self, cols: Optional[List[str]] = None):
        self.cols = cols

    def fit(self, X: pd.DataFrame, y=None):
        if self.cols is None:
            self.cols = self._auto_detect(X)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if not self.cols:
            result["hazardous_chemical_flag"] = 0
            return result

        or_val = pd.Series(0, index=X.index)
        for col in self.cols:
            if col in X.columns:
                val = X[col].apply(self._to_binary)
                or_val = or_val | val
        result["hazardous_chemical_flag"] = or_val.astype(int)
        return result

    def _auto_detect(self, X: pd.DataFrame) -> List[str]:
        patterns = ["危化品", "危险化学品", "化学品", "hazardous_chemical", "chemical"]
        found = []
        for c in X.columns:
            for p in patterns:
                if p in c:
                    found.append(c)
                    break
        return found

    def _to_binary(self, val: Any) -> int:
        if pd.isna(val):
            return 0
        s = str(val).strip().lower()
        if s in {"1", "是", "有", "true", "yes"}:
            return 1
        try:
            return 1 if float(s) > 0 else 0
        except ValueError:
            return 0


class TimeDecayWeightTransformer(BaseEstimator, TransformerMixin):
    """
    时间衰减加权器
    当年 1.0 / 前一年 0.7 / 前两年 0.5
    """

    def __init__(
        self,
        time_col: Optional[str] = None,
        value_cols: Optional[List[str]] = None,
        reference_year: Optional[int] = None,
    ):
        self.time_col = time_col
        self.value_cols = value_cols or []
        self.reference_year = reference_year

    def fit(self, X: pd.DataFrame, y=None):
        if self.time_col is None:
            for c in X.columns:
                if "时间" in c or "年份" in c or "year" in c.lower():
                    self.time_col = c
                    break
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if self.time_col is None or self.time_col not in X.columns:
            # 若无时间列，直接返回原数值列
            for col in self.value_cols:
                if col in X.columns:
                    result[col] = pd.to_numeric(X[col], errors="coerce").fillna(0)
            return result

        t = pd.to_datetime(X[self.time_col], errors="coerce")
        years = t.dt.year
        ref = self.reference_year or (pd.Timestamp.now().year)

        year_diff = (ref - years).clip(lower=0)
        weights = year_diff.map({0: 1.0, 1: 0.7}).fillna(0.5)
        # 超过两年统一 0.5
        weights[year_diff >= 2] = 0.5

        for col in self.value_cols:
            if col in X.columns:
                val = pd.to_numeric(X[col], errors="coerce").fillna(0)
                result[f"{col}_decay_weighted"] = val * weights
        return result


class GeoFenceTransformer(BaseEstimator, TransformerMixin):
    """
    地理围栏特征生成器
    比对经纬度是否在化工园区范围内
    """

    def __init__(
        self,
        lon_col: Optional[str] = None,
        lat_col: Optional[str] = None,
        fence_polygons: Optional[List[List[Tuple[float, float]]]] = None,
    ):
        self.lon_col = lon_col
        self.lat_col = lat_col
        self.fence_polygons = fence_polygons

    def fit(self, X: pd.DataFrame, y=None):
        if self.lon_col is None:
            for c in X.columns:
                if "经度" in c or "lon" in c.lower():
                    self.lon_col = c
                    break
        if self.lat_col is None:
            for c in X.columns:
                if "纬度" in c or "lat" in c.lower():
                    self.lat_col = c
                    break
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if self.lon_col is None or self.lat_col is None:
            result["in_chemical_park"] = 0
            return result

        lon = pd.to_numeric(X[self.lon_col], errors="coerce")
        lat = pd.to_numeric(X[self.lat_col], errors="coerce")

        polygons = self.fence_polygons or []
        if not polygons:
            # 默认示例：使用一个近似苏州化工园区范围的矩形
            # 实际部署时应替换为真实园区边界坐标串
            result["in_chemical_park"] = 0
            return result

        inside = pd.Series(0, index=X.index)
        for i in X.index:
            if pd.notna(lon.loc[i]) and pd.notna(lat.loc[i]):
                if self._point_in_polygons(lon.loc[i], lat.loc[i], polygons):
                    inside.loc[i] = 1
        result["in_chemical_park"] = inside.astype(int)
        return result

    def _point_in_polygons(self, lon: float, lat: float, polygons: List[List[Tuple[float, float]]]) -> bool:
        for poly in polygons:
            if self._point_in_polygon(lon, lat, poly):
                return True
        return False

    @staticmethod
    def _point_in_polygon(x: float, y: float, polygon: List[Tuple[float, float]]) -> bool:
        n = len(polygon)
        inside = False
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside


class EnterpriseAggregator(BaseEstimator, TransformerMixin):
    """
    按企业聚合特征生成器
    隐患加权、文书加权（立案 > 检查）
    """

    DEFAULT_DOC_WEIGHTS = {"立案": 3.0, "处罚": 2.5, "检查": 1.0, "文书": 1.5}

    def __init__(
        self,
        enterprise_id_col: Optional[str] = None,
        hazard_cols: Optional[List[str]] = None,
        document_cols: Optional[List[str]] = None,
        document_weights: Optional[Dict[str, float]] = None,
    ):
        self.enterprise_id_col = enterprise_id_col
        self.hazard_cols = hazard_cols
        self.document_cols = document_cols
        self.document_weights = document_weights

    def fit(self, X: pd.DataFrame, y=None):
        if self.enterprise_id_col is None:
            for c in X.columns:
                if "企业" in c and ("ID" in c or "id" in c or "代码" in c):
                    self.enterprise_id_col = c
                    break
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if self.enterprise_id_col is None or self.enterprise_id_col not in X.columns:
            result["enterprise_hazard_score"] = 0
            result["enterprise_doc_score"] = 0
            return result

        ent_id = X[self.enterprise_id_col]

        hazard_cols = self.hazard_cols or []
        document_cols = self.document_cols or []
        doc_weights = self.document_weights or self.DEFAULT_DOC_WEIGHTS

        # 隐患加权求和
        hazard_sum = pd.Series(0.0, index=X.index)
        for col in hazard_cols:
            if col in X.columns:
                hazard_sum += pd.to_numeric(X[col], errors="coerce").fillna(0)
        result["enterprise_hazard_score"] = hazard_sum

        # 文书加权：根据列名关键词匹配权重
        doc_score = pd.Series(0.0, index=X.index)
        for col in document_cols:
            if col not in X.columns:
                continue
            weight = 1.0
            for keyword, w in doc_weights.items():
                if keyword in col:
                    weight = w
                    break
            doc_score += pd.to_numeric(X[col], errors="coerce").fillna(0) * weight
        result["enterprise_doc_score"] = doc_score

        # 按企业聚合（若存在重复企业，取均值或最大值的指标化）
        # 这里保留原始行级特征，下游可进一步聚合
        return result


class DataCredibilityTransformer(BaseEstimator, TransformerMixin):
    """
    数据可信度系数生成器
    检查来源映射：4>3>2>1
    """

    DEFAULT_SOURCE_MAP = {
        "4": 4.0, "执法": 4.0, "专项检查": 4.0,
        "3": 3.0, "整改复查": 3.0, "立案": 3.0,
        "2": 2.0, "日常检查": 2.0, "定期检查": 2.0,
        "1": 1.0, "企业自报": 1.0, "自查": 1.0,
    }

    def __init__(
        self,
        source_col: Optional[str] = None,
        source_map: Optional[Dict[str, float]] = None,
    ):
        self.source_col = source_col
        self.source_map = source_map

    def fit(self, X: pd.DataFrame, y=None):
        if self.source_col is None:
            for c in X.columns:
                if "来源" in c or "source" in c.lower():
                    self.source_col = c
                    break
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=X.index)
        if self.source_col is None or self.source_col not in X.columns:
            result["data_credibility"] = 1.0
            return result

        source_map = self.source_map or self.DEFAULT_SOURCE_MAP

        def _map(val):
            if pd.isna(val):
                return 1.0
            s = str(val).strip()
            if s in source_map:
                return source_map[s]
            # 模糊匹配
            for k, v in source_map.items():
                if k in s:
                    return v
            return 1.0

        result["data_credibility"] = X[self.source_col].apply(_map)
        return result


def csv_to_markdown_table(csv_path: str, max_rows: int = 100, delimiter: str = ",") -> str:
    """
    将 CSV 文件转换为 Markdown 表格字符串
    
    Args:
        csv_path: CSV 文件路径
        max_rows: 最大输出行数（含表头）
        delimiter: 分隔符，默认为逗号
    
    Returns:
        Markdown 表格字符串
    """
    import csv as csv_module
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv_module.reader(f, delimiter=delimiter)
        rows = list(reader)
    
    if not rows:
        return ""
    
    rows = rows[:max_rows]
    header = rows[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


class FeatureEngineeringPipeline:
    """
    特征工程全流程管理
    严格对齐建设方案 0.1 节
    """

    def __init__(self):
        config = get_config()
        self.config = config.features
        self.pipeline: Optional[Pipeline] = None
        # 不在初始化时构建pipeline，延迟到fit_transform时构建

    def _build_pipeline(self, available_columns: Optional[List[str]] = None) -> None:
        """构建预处理 Pipeline，只使用实际存在的列"""
        # 根据可用列动态选择
        def _filter(cols: List[str]) -> List[str]:
            if available_columns is None:
                return cols
            return [c for c in cols if c in available_columns]

        # 缺失值处理（只处理存在的列）
        mgmt_fields = _filter(self.config.missing_value_strategy.get("management_fields", {}).get("fields", []))
        obj_fields = _filter(self.config.missing_value_strategy.get("objective_fields", {}).get("fields", []))
        missing_handler = MissingValueHandler(
            management_fields=mgmt_fields,
            objective_fields=obj_fields,
        )

        # 列变换器
        transformers = []

        binary_cols = _filter(self.config.binary_columns)
        if binary_cols:
            transformers.append(("binary", BinaryEncoder(), binary_cols))

        numeric_cols = _filter(self.config.numeric_columns)
        if numeric_cols:
            transformers.append(
                ("numeric", NumericTransformer(clip_quantile=self.config.outlier_clip_quantile),
                 numeric_cols)
            )

        enum_cols = _filter(self.config.enum_columns)
        if enum_cols:
            transformers.append(("enum", EnumRiskMapper(), enum_cols))

        text_cols = _filter(self.config.text_columns)
        if text_cols:
            transformers.append(("text", TextRiskExtractor(), text_cols))

        industry_cols = _filter(self.config.industry_columns)
        if industry_cols:
            transformers.append(("industry", IndustryRiskCoefficient(), industry_cols))

        # ===== 特殊逻辑特征工程 =====
        # 干湿除尘比例
        dust_cols = [c for c in (available_columns or []) if "除尘" in c]
        if dust_cols:
            transformers.append(("dust_ratio", DustRemovalRatioTransformer(), dust_cols))

        # 有限空间 OR 逻辑
        confined_cols = [c for c in (available_columns or []) if any(k in c for k in ["有限空间", "密闭空间", "受限空间", "空间作业"])]
        if confined_cols:
            transformers.append(("confined_space", ConfinedSpaceORTransformer(cols=confined_cols), confined_cols))

        # 危化品 OR 逻辑
        chem_cols = [c for c in (available_columns or []) if any(k in c for k in ["危化品", "危险化学品", "化学品"])]
        if chem_cols:
            transformers.append(("hazardous_chem", HazardousChemicalORTransformer(cols=chem_cols), chem_cols))

        # 时间衰减加权：自动探测数值列（排除ID类）
        time_col = None
        for c in available_columns or []:
            if "时间" in c or "年份" in c or "year" in c.lower():
                time_col = c
                break
        if time_col:
            value_candidates = [c for c in (available_columns or []) if c not in binary_cols + enum_cols + text_cols + industry_cols and c != time_col]
            # 只选择少量数值列避免维度爆炸
            decay_value_cols = [c for c in value_candidates if any(k in c for k in ["隐患", "事故", "风险", "处罚", "检查", "投入"])]
            if decay_value_cols:
                transformers.append(("time_decay", TimeDecayWeightTransformer(time_col=time_col, value_cols=decay_value_cols), [time_col] + decay_value_cols))

        # 地理围栏：探测经纬度列
        lon_col = next((c for c in (available_columns or []) if "经度" in c or "lon" in c.lower()), None)
        lat_col = next((c for c in (available_columns or []) if "纬度" in c or "lat" in c.lower()), None)
        if lon_col and lat_col:
            transformers.append(("geo_fence", GeoFenceTransformer(lon_col=lon_col, lat_col=lat_col), [lon_col, lat_col]))

        # 按企业聚合：探测企业ID列和隐患/文书列
        ent_id_col = next((c for c in (available_columns or []) if "企业" in c and ("ID" in c or "id" in c or "代码" in c)), None)
        if ent_id_col:
            hazard_candidates = [c for c in (available_columns or []) if "隐患" in c or "风险" in c or "事故" in c]
            doc_candidates = [c for c in (available_columns or []) if "文书" in c or "立案" in c or "检查" in c or "处罚" in c]
            agg_cols = [ent_id_col] + hazard_candidates + doc_candidates
            if len(agg_cols) > 1:
                transformers.append(("enterprise_agg", EnterpriseAggregator(enterprise_id_col=ent_id_col, hazard_cols=hazard_candidates, document_cols=doc_candidates), agg_cols))

        # 数据可信度系数
        source_col = next((c for c in (available_columns or []) if "来源" in c or "source" in c.lower()), None)
        if source_col:
            transformers.append(("credibility", DataCredibilityTransformer(source_col=source_col), [source_col]))

        column_transformer = ColumnTransformer(
            transformers=transformers,
            remainder="drop",  # 主键字段不参与评分
            verbose_feature_names_out=False,
        )

        self.pipeline = Pipeline([
            ("missing_handler", missing_handler),
            ("feature_transform", column_transformer),
        ])

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """拟合并转换数据"""
        try:
            # 动态构建 pipeline，只使用实际存在的列
            self._build_pipeline(available_columns=list(df.columns))
            # 使用局部变量，避免 self.pipeline 被意外修改
            pipeline = self.pipeline
            result = pipeline.fit_transform(df)
            # 获取特征
            feature_names = self._get_feature_names(list(df.columns))
            result_df = pd.DataFrame(result, columns=feature_names, index=df.index)
            logger.info(f"特征工程完成，输出形状: {result_df.shape}")
            return result_df
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise FeatureEngineeringError(f"特征工程失败: {e}")

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """转换数据（需先 fit）"""
        try:
            result = self.pipeline.transform(df)
            feature_names = self._get_feature_names(list(df.columns))
            return pd.DataFrame(result, columns=feature_names, index=df.index)
        except Exception as e:
            raise FeatureEngineeringError(f"特征转换失败: {e}")

    def _get_feature_names(self, available_columns: Optional[List[str]] = None) -> List[str]:
        """获取变换后的特征名"""
        def _filter(cols: List[str]) -> List[str]:
            if available_columns is None:
                return cols
            return [c for c in cols if c in available_columns]

        names = []
        names.extend(_filter(self.config.binary_columns))
        names.extend(_filter(self.config.numeric_columns))
        names.extend(_filter(self.config.enum_columns))
        text_cols = _filter(self.config.text_columns)
        for col in text_cols:
            names.extend([f"{col}_completeness", f"{col}_risk_words"])
        if _filter(self.config.industry_columns):
            names.append("industry_risk_coefficient")

        # 特殊逻辑特征名
        dust_cols = [c for c in (available_columns or []) if "除尘" in c]
        if dust_cols:
            names.extend(["dry_removal_ratio", "wet_removal_ratio"])

        confined_cols = [c for c in (available_columns or []) if any(k in c for k in ["有限空间", "密闭空间", "受限空间", "空间作业"])]
        if confined_cols:
            names.append("confined_space_flag")

        chem_cols = [c for c in (available_columns or []) if any(k in c for k in ["危化品", "危险化学品", "化学品"])]
        if chem_cols:
            names.append("hazardous_chemical_flag")

        time_col = next((c for c in (available_columns or []) if "时间" in c or "年份" in c or "year" in c.lower()), None)
        if time_col:
            value_candidates = [c for c in (available_columns or []) if c not in self.config.binary_columns + self.config.enum_columns + self.config.text_columns + self.config.industry_columns and c != time_col]
            decay_value_cols = [c for c in value_candidates if any(k in c for k in ["隐患", "事故", "风险", "处罚", "检查", "投入"])]
            for col in decay_value_cols:
                names.append(f"{col}_decay_weighted")

        lon_col = next((c for c in (available_columns or []) if "经度" in c or "lon" in c.lower()), None)
        lat_col = next((c for c in (available_columns or []) if "纬度" in c or "lat" in c.lower()), None)
        if lon_col and lat_col:
            names.append("in_chemical_park")

        ent_id_col = next((c for c in (available_columns or []) if "企业" in c and ("ID" in c or "id" in c or "代码" in c)), None)
        if ent_id_col:
            names.extend(["enterprise_hazard_score", "enterprise_doc_score"])

        source_col = next((c for c in (available_columns or []) if "来源" in c or "source" in c.lower()), None)
        if source_col:
            names.append("data_credibility")

        return names

    def save(self, path: str) -> None:
        """序列化 Pipeline"""
        joblib.dump(self.pipeline, path)
        logger.info(f"Pipeline 已保存至 {path}")

    def load(self, path: str) -> None:
        """加载序列化的 Pipeline"""
        self.pipeline = joblib.load(path)
        logger.info(f"Pipeline 已从 {path} 加载")
