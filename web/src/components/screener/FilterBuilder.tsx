import FilterRule, { type FieldDef, type Rule } from "./FilterRule";

interface Props {
  rules: Rule[];
  fields: FieldDef[];
  onChange: (rules: Rule[]) => void;
}

export default function FilterBuilder({ rules, fields, onChange }: Props) {
  const handleRuleChange = (index: number, rule: Rule) => {
    const next = [...rules];
    next[index] = rule;
    onChange(next);
  };

  const handleRemove = (index: number) => {
    onChange(rules.filter((_, i) => i !== index));
  };

  const addRule = () => {
    onChange([...rules, { field: "", op: "gt", value: "" }]);
  };

  return (
    <div className="space-y-2">
      {rules.length === 0 && (
        <p className="text-sm text-gray-600 py-1">
          No filters applied — showing all companies. Add filters to narrow results.
        </p>
      )}
      {rules.map((rule, i) => (
        <FilterRule
          key={i}
          rule={rule}
          index={i}
          fields={fields}
          onChange={handleRuleChange}
          onRemove={handleRemove}
        />
      ))}
      <button
        onClick={addRule}
        className="flex items-center gap-1.5 rounded-lg border border-dashed border-gray-700 px-3 py-1.5 text-sm text-gray-500 hover:border-gray-500 hover:text-white transition-colors"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
        Add Filter
      </button>
    </div>
  );
}
