"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { API_URLS } from "@/lib/config";

interface FeatureComparisonRow {
  feature: string;
  label: string;
  prior_value: number;
  current_value: number;
  delta: number;
}

interface ComparisonInfo {
  prior_run_id: string;
  prior_created_at: number;
  prior_support_pct: number;
  delta_support_pct_points: number;
  status: "converged" | "diverging";
  feature_comparison: FeatureComparisonRow[];
}

interface HistoryRun {
  run_id: string;
  created_at: number;
  support_pct: number | null;
  persona_name: string;
  values: Record<string, number | null>;
  display_values: Record<string, string>;
  narrative: string;
}

interface HistoryInfo {
  cluster_features: string[];
  profile_features: string[];
  feature_labels: Record<string, string>;
  runs: HistoryRun[];
  narratives_identical: boolean;
  cluster_stable: boolean;
  profile_stable: boolean;
}

interface StatsRow {
  feature: string;
  label: string;
  value: number;
  value_display?: string;
  benchmark: number;
  benchmark_display?: string;
  dev_pct: number | null;
  is_profile_attr: boolean;
}

interface PersonaFeedItem {
  run_id: string;
  created_at: number;
  cluster_id: number | null;
  persona_name: string;
  support: number | null;
  support_pct: number | null;
  churn_driver: string | null;
  risk: string | null;
  severity: string | null;
  priority_score: number | null;
  description: string;
  stats_table: StatsRow[];
  comparison: ComparisonInfo | null;
  history: HistoryInfo | null;
  total_occurrences: number | null;
  first_seen_at: number | null;
  profile_backfilled_from: { run_id: string; created_at: number } | null;
}

interface LoopStatus {
  running: boolean;
  run_count: number;
  error_count: number;
  last_run_at: number | null;
  last_error: string | null;
}

const POLL_INTERVAL_MS = 7000;

function formatTime(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function formatPct(pct: number | null): string {
  if (pct === null || pct === undefined) return "—";
  return `${(pct * 100).toFixed(1)}%`;
}

function featureLabel(feature: string, label?: string | null): string {
  return label && label !== feature ? `${feature} (${label})` : feature;
}

function renderCompactStatsTable(stats: StatsRow[], features: string[], title: string, note?: string) {
  const rows = features
    .map((f) => stats.find((s) => s.feature === f))
    .filter((s): s is StatsRow => !!s);
  if (rows.length === 0) return null;
  return (
    <div className="overflow-x-auto pt-2">
      <p className="pb-1 text-xs font-medium text-foreground/70">
        {title}
        {note && <span className="font-normal text-muted-foreground"> — {note}</span>}
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pr-4 font-medium">Feature</th>
            <th className="pr-4 font-medium">Trung bình trong cụm</th>
            <th className="pr-4 font-medium">Trung bình trên toàn bộ data</th>
            <th className="font-medium">Chênh lệch</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.feature}>
              <td className="pr-4 py-0.5 text-muted-foreground">{featureLabel(row.feature, row.label)}</td>
              <td className="pr-4 py-0.5">{row.value_display ?? row.value}</td>
              <td className="pr-4 py-0.5 text-muted-foreground">{row.benchmark_display ?? row.benchmark}</td>
              <td className="py-0.5">
                {typeof row.dev_pct === "number" ? `${row.dev_pct > 0 ? "+" : ""}${row.dev_pct}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderFeatureHistoryTable(history: HistoryInfo, features: string[], title: string) {
  if (features.length === 0) return null;
  return (
    <div className="overflow-x-auto pt-2">
      <p className="pb-1 text-xs font-medium text-foreground/70">{title}</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pr-4 font-medium">Feature</th>
            {history.runs.map((r) => (
              <th key={r.run_id} className="pr-4 font-medium whitespace-nowrap">
                {formatTime(r.created_at)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="pr-4 py-0.5 font-medium">support_pct</td>
            {history.runs.map((r) => (
              <td key={r.run_id} className="pr-4 py-0.5">
                {formatPct(r.support_pct)}
              </td>
            ))}
          </tr>
          {features.map((f) => (
            <tr key={f}>
              <td className="pr-4 py-0.5 text-muted-foreground">
                {featureLabel(f, history.feature_labels[f])}
              </td>
              {history.runs.map((r) => (
                <td key={r.run_id} className="pr-4 py-0.5">
                  {r.display_values[f] ?? (r.values[f] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ConvergencePage() {
  const [personas, setPersonas] = useState<PersonaFeedItem[]>([]);
  const [status, setStatus] = useState<LoopStatus | null>(null);
  const [markdown, setMarkdown] = useState<string>("");
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedNarrativeHistory, setExpandedNarrativeHistory] = useState<Set<string>>(new Set());

  const toggleNarrativeHistory = (key: string) => {
    setExpandedNarrativeHistory((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [personasRes, statusRes, markdownRes] = await Promise.all([
          fetch(API_URLS.CONVERGENCE_PERSONAS),
          fetch(API_URLS.CONVERGENCE_STATUS),
          fetch(API_URLS.CONVERGENCE_MARKDOWN),
        ]);
        if (!personasRes.ok || !statusRes.ok) {
          throw new Error("Request failed");
        }
        const personasData = await personasRes.json();
        const statusData = await statusRes.json();
        const markdownText = markdownRes.ok ? await markdownRes.text() : "";
        if (!cancelled) {
          setPersonas(personasData.personas || []);
          setStatus(statusData);
          setMarkdown(markdownText);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError("Không thể kết nối tới backend.");
      }
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <main className="min-h-screen bg-background p-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <div>
          <h1 className="text-xl font-semibold">Persona Convergence Feed</h1>
          <p className="text-sm text-muted-foreground">
            20 persona duy nhất gần nhất (không lặp lại) từ vòng lặp chạy nền liên tục trên dataset cố định.
          </p>
        </div>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">
              File markdown tổng hợp (workspace/convergence/generated/convergence_personas_latest.md)
            </CardTitle>
            <button
              className="text-xs text-muted-foreground underline"
              onClick={() => setShowMarkdown((v) => !v)}
            >
              {showMarkdown ? "Thu gọn" : "Xem"}
            </button>
          </CardHeader>
          {showMarkdown && (
            <CardContent className="max-h-96 overflow-auto border-t pt-3">
              {markdown ? (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                </div>
              ) : (
                <span className="text-sm text-muted-foreground">Chưa có nội dung.</span>
              )}
            </CardContent>
          )}
        </Card>

        <Card>
          <CardContent className="flex flex-wrap items-center gap-4 py-4 text-sm">
            {status ? (
              <>
                <Badge variant={status.running ? "default" : "secondary"}>
                  {status.running ? "Đang chạy" : "Đã dừng"}
                </Badge>
                <span>Số lần chạy: {status.run_count}</span>
                <span>Lỗi: {status.error_count}</span>
                <span>Lần chạy gần nhất: {formatTime(status.last_run_at)}</span>
                {status.last_error && (
                  <span className="text-destructive">Lỗi gần nhất: {status.last_error}</span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">Đang tải trạng thái...</span>
            )}
          </CardContent>
        </Card>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {personas.length === 0 && !error && (
          <p className="text-sm text-muted-foreground">
            Chưa có persona nào được sinh ra. Đang chờ vòng lặp chạy xong lượt đầu tiên...
          </p>
        )}

        <div className="space-y-3">
          {personas.map((p, idx) => (
            <Card key={`${p.run_id}-${p.cluster_id}-${idx}`}>
              <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2">
                <div>
                  <CardTitle className="text-base">{p.persona_name}</CardTitle>
                  <p className="text-xs text-muted-foreground">
                    Run {p.run_id.slice(0, 8)} · {formatTime(p.created_at)}
                    {p.total_occurrences && p.total_occurrences > 1 && (
                      <> · Đã xuất hiện {p.total_occurrences} lượt kể từ {formatTime(p.first_seen_at)}</>
                    )}
                  </p>
                </div>
                {p.comparison ? (
                  <Badge variant={p.comparison.status === "converged" ? "default" : "destructive"}>
                    {p.comparison.status === "converged" ? "▲ Hội tụ" : "▼ Đang dao động"}{" "}
                    {p.comparison.delta_support_pct_points > 0 ? "+" : ""}
                    {p.comparison.delta_support_pct_points.toFixed(1)}pp
                  </Badge>
                ) : (
                  <Badge variant="outline">Lần xuất hiện đầu tiên</Badge>
                )}
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {p.description && (
                  <p className="text-foreground/90">{p.description}</p>
                )}
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
                  <span>Support: {p.support ?? "—"} ({formatPct(p.support_pct)})</span>
                  {p.churn_driver && <span>Churn driver: {p.churn_driver}</span>}
                  {p.risk && <span>Risk: {p.risk}</span>}
                  {p.severity && <span>Severity: {p.severity}</span>}
                </div>
                {p.profile_backfilled_from && (
                  <p className="text-xs text-amber-600 dark:text-amber-500">
                    ⓘ Lần chạy mới nhất không tính được nhóm chỉ số phụ (profile attributes) —
                    đang hiển thị bản đầy đủ gần nhất của cùng cụm này (lượt{" "}
                    {formatTime(p.profile_backfilled_from.created_at)}). Support % vẫn của lần chạy mới nhất.
                  </p>
                )}

                {p.history && p.history.runs.length > 1 ? (
                  <div className="pt-1">
                    <p className="pb-1 text-xs text-muted-foreground">
                      So sánh chỉ số qua {p.history.runs.length} lần chạy gần nhất — persona này được nhận diện
                      là CÙNG 1 cụm (theo dấu vân tay thống kê) ở mọi cột dưới đây
                    </p>
                    {p.history.cluster_stable
                      ? renderCompactStatsTable(
                          p.stats_table,
                          p.history.cluster_features,
                          "Feature đóng góp phân cụm (dùng để train KMeans)",
                          `giống hệt nhau ở cả ${p.history.runs.length} lần chạy — không lặp lại từng cột`
                        )
                      : renderFeatureHistoryTable(
                          p.history,
                          p.history.cluster_features,
                          "Feature đóng góp phân cụm (dùng để train KMeans)"
                        )}
                    {p.history.profile_stable
                      ? renderCompactStatsTable(
                          p.stats_table,
                          p.history.profile_features,
                          "Feature đóng góp phân tích persona (KHÔNG dùng để phân cụm)",
                          `giống hệt nhau ở cả ${p.history.runs.length} lần chạy — không lặp lại từng cột`
                        )
                      : renderFeatureHistoryTable(
                          p.history,
                          p.history.profile_features,
                          "Feature đóng góp phân tích persona (KHÔNG dùng để phân cụm)"
                        )}
                  </div>
                ) : null}

                {p.history && p.history.runs.length > 1 && (() => {
                  const cardKey = `${p.run_id}-${p.cluster_id}-${idx}`;
                  const expanded = expandedNarrativeHistory.has(cardKey);
                  return (
                    <div className="pt-1">
                      {p.history.narratives_identical ? (
                        <p className="text-xs text-muted-foreground">
                          Mô tả (narrative) giống hệt nhau ở cả {p.history.runs.length} lần chạy trên —
                          LLM viết lại nhất quán dù được gọi riêng mỗi lần.
                        </p>
                      ) : (
                        <>
                          <button
                            className="text-xs text-muted-foreground underline"
                            onClick={() => toggleNarrativeHistory(cardKey)}
                          >
                            {expanded ? "Thu gọn" : "Xem"} mô tả qua {p.history.runs.length} lần chạy — LỆCH NHAU dù chỉ số giống nhau
                          </button>
                          {expanded && (
                            <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                              {p.history.runs.map((r) => (
                                <li key={r.run_id}>
                                  <span className="font-medium">{formatTime(r.created_at)}:</span> {r.narrative}
                                </li>
                              ))}
                            </ul>
                          )}
                        </>
                      )}
                    </div>
                  );
                })()}

                {!p.history && p.stats_table && p.stats_table.length > 0 && (
                  <>
                    {renderCompactStatsTable(
                      p.stats_table,
                      p.stats_table.filter((s) => !s.is_profile_attr).map((s) => s.feature),
                      "Feature đóng góp phân cụm (dùng để train KMeans)"
                    )}
                    {renderCompactStatsTable(
                      p.stats_table,
                      p.stats_table.filter((s) => s.is_profile_attr).map((s) => s.feature),
                      "Feature đóng góp phân tích persona (KHÔNG dùng để phân cụm)"
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </main>
  );
}
