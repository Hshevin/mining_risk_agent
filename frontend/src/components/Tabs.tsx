import type { ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
}

interface Props {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  children?: ReactNode;
}

export default function Tabs({ tabs, active, onChange }: Props) {
  return (
    <div className="tabs-bar">
      {tabs.map((t) => (
        <button
          key={t.id}
          className={`tab-button ${t.id === active ? "active" : ""}`}
          onClick={() => onChange(t.id)}
          type="button"
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
