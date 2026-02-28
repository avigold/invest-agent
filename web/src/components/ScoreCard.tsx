function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

interface ScoreCardProps {
  label: string;
  score: number;
  maxScore?: number;
}

export default function ScoreCard({
  label,
  score,
  maxScore = 100,
}: ScoreCardProps) {
  const pct = Math.min(100, (score / maxScore) * 100);

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
      <div className="mb-1 text-xs font-medium uppercase text-gray-400">
        {label}
      </div>
      <div className={`text-2xl font-bold ${scoreColor(score)}`}>
        {score.toFixed(1)}
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-gray-700">
        <div
          className={`h-1.5 rounded-full ${barColor(score)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
