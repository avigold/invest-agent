export interface FieldDef {
  key: string;
  label: string;
  type: "numeric" | "categorical";
  category: string;
  format?: string;
  values?: string[];
}

export interface Rule {
  field: string;
  op: string;
  value: unknown;
}

interface Props {
  rule: Rule;
  index: number;
  fields: FieldDef[];
  onChange: (index: number, rule: Rule) => void;
  onRemove: (index: number) => void;
}

const NUMERIC_OPS = [
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: "\u2265" },
  { value: "lte", label: "\u2264" },
  { value: "eq", label: "=" },
  { value: "between", label: "between" },
];

const CAT_OPS = [
  { value: "in", label: "is any of" },
  { value: "not_in", label: "is not" },
];

function groupFields(fields: FieldDef[]): Record<string, FieldDef[]> {
  const groups: Record<string, FieldDef[]> = {};
  for (const f of fields) {
    (groups[f.category] ??= []).push(f);
  }
  return groups;
}

const selectCls =
  "rounded border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none";
const inputCls =
  "rounded border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none";

export default function FilterRule({ rule, index, fields, onChange, onRemove }: Props) {
  const fieldDef = fields.find((f) => f.key === rule.field);
  const isNumeric = fieldDef?.type === "numeric";
  const ops = isNumeric ? NUMERIC_OPS : CAT_OPS;
  const grouped = groupFields(fields);

  const update = (patch: Partial<Rule>) => onChange(index, { ...rule, ...patch });

  const handleFieldChange = (key: string) => {
    const fd = fields.find((f) => f.key === key);
    update({
      field: key,
      op: fd?.type === "numeric" ? "gt" : "in",
      value: fd?.type === "numeric" ? "" : [],
    });
  };

  return (
    <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2">
      <select value={rule.field} onChange={(e) => handleFieldChange(e.target.value)} className={selectCls}>
        <option value="">Field...</option>
        {Object.entries(grouped).map(([cat, flds]) => (
          <optgroup key={cat} label={cat}>
            {flds.map((f) => (
              <option key={f.key} value={f.key}>{f.label}</option>
            ))}
          </optgroup>
        ))}
      </select>

      <select value={rule.op} onChange={(e) => update({ op: e.target.value })} className={selectCls}>
        {ops.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {isNumeric && rule.op === "between" ? (
        <div className="flex items-center gap-1">
          <input
            type="number"
            step="any"
            value={Array.isArray(rule.value) ? (rule.value as number[])[0] ?? "" : ""}
            onChange={(e) => {
              const arr = Array.isArray(rule.value) ? [...(rule.value as number[])] : [0, 0];
              arr[0] = e.target.value === "" ? 0 : Number(e.target.value);
              update({ value: arr });
            }}
            placeholder="min"
            className={`w-20 ${inputCls}`}
          />
          <span className="text-xs text-gray-500">&ndash;</span>
          <input
            type="number"
            step="any"
            value={Array.isArray(rule.value) ? (rule.value as number[])[1] ?? "" : ""}
            onChange={(e) => {
              const arr = Array.isArray(rule.value) ? [...(rule.value as number[])] : [0, 0];
              arr[1] = e.target.value === "" ? 0 : Number(e.target.value);
              update({ value: arr });
            }}
            placeholder="max"
            className={`w-20 ${inputCls}`}
          />
        </div>
      ) : isNumeric ? (
        <input
          type="number"
          step="any"
          value={rule.value as string}
          onChange={(e) => update({ value: e.target.value === "" ? "" : Number(e.target.value) })}
          placeholder="Value"
          className={`w-24 ${inputCls}`}
        />
      ) : (
        <select
          multiple
          value={Array.isArray(rule.value) ? (rule.value as string[]) : []}
          onChange={(e) => {
            const vals = Array.from(e.target.selectedOptions, (o) => o.value);
            update({ value: vals });
          }}
          className={`min-w-[140px] max-h-[80px] ${selectCls}`}
        >
          {(fieldDef?.values ?? []).map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      )}

      <button
        onClick={() => onRemove(index)}
        className="ml-auto rounded p-1 text-gray-600 hover:text-red-400 transition-colors"
        title="Remove"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
