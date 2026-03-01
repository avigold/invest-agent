interface WeightSliderProps {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
  description?: string;
  displayFormat?: (value: number) => string;
}

export default function WeightSlider({
  label,
  value,
  min = 0,
  max = 1,
  step = 0.01,
  onChange,
  description,
  displayFormat,
}: WeightSliderProps) {
  const display = displayFormat
    ? displayFormat(value)
    : max <= 1
      ? `${(value * 100).toFixed(0)}%`
      : value.toFixed(1);

  return (
    <div className="flex items-center gap-3">
      <div className="min-w-[140px]">
        <div className="text-sm text-gray-300">{label}</div>
        {description && (
          <div className="text-xs text-gray-600">{description}</div>
        )}
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="flex-1 h-1.5 appearance-none rounded-full bg-gray-700 accent-blue-500 cursor-pointer"
      />
      <div className="w-12 text-right font-mono text-sm text-gray-400">
        {display}
      </div>
    </div>
  );
}
