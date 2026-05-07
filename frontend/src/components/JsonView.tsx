interface Props {
  data: unknown;
  maxHeight?: number | string;
}

export default function JsonView({ data, maxHeight }: Props) {
  const str = JSON.stringify(data, null, 2);
  return (
    <pre className="json-code-block" style={maxHeight ? { maxHeight } : undefined}>
      {str}
    </pre>
  );
}
