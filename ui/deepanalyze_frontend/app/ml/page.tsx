"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Database,
  Download,
  Loader2,
  Play,
  RefreshCw,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { API_URLS, buildApiUrlWithParams } from "@/lib/config";

type Task = "classification" | "regression";
type H2OAlgorithm = "DRF" | "GLM" | "XGBoost" | "GBM" | "DeepLearning" | "StackedEnsemble";

interface DatasetInfo {
  id: string;
  name: string;
  size: number;
  created_at?: string;
  columns: string[];
  dtypes: Record<string, string>;
  row_count?: number;
}

interface ArtifactInfo {
  path: string;
  download_url: string;
  preview_url?: string | null;
}

interface ExperimentResult {
  leader_model_id: string;
  metrics: Record<string, unknown>;
  leaderboard: Array<Record<string, unknown>>;
  variable_importance: Array<Record<string, unknown>>;
  row_counts: Record<string, number>;
  artifacts: Record<string, ArtifactInfo>;
}

interface ExperimentInfo {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  dataset_id: string;
  dataset_name: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  config: {
    target: string;
    task: Task;
    metric: string;
    time_budget: number;
    max_models?: number | null;
    balance_classes: boolean;
    include_algos?: H2OAlgorithm[];
    distribution?: string;
    stopping_metric?: string;
    max_runtime_per_model?: number | null;
    preprocessing?: string[];
  };
  result?: ExperimentResult | null;
  error?: string | null;
}

interface HealthInfo {
  installed: boolean;
  connected: boolean;
  ready: boolean;
  version?: string;
  mode?: string;
  error?: string;
}

const sessionId = "default";
const h2oAlgorithms: Array<{ value: H2OAlgorithm; label: string }> = [
  { value: "GBM", label: "GBM" },
  { value: "XGBoost", label: "XGBoost" },
  { value: "DRF", label: "Random Forest" },
  { value: "GLM", label: "GLM" },
  { value: "DeepLearning", label: "Deep Learning" },
  { value: "StackedEnsemble", label: "Stacked Ensemble" },
];
const defaultAlgorithms = h2oAlgorithms.map(({ value }) => value);
const formatBytes = (bytes: number) =>
  bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

const formatMetric = (value: unknown) => {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(5);
  if (value === null || value === undefined) return "—";
  return String(value);
};

const artifactLabel: Record<string, string> = {
  binary_model: "H2O model",
  mojo: "MOJO",
  test_predictions: "Test predictions",
};

type ApiPayload = Record<string, any>;

const readApiResponse = async (response: Response): Promise<ApiPayload> => {
  const rawBody = await response.text();
  if (!rawBody.trim()) return {};

  try {
    const parsed: unknown = JSON.parse(rawBody);
    return typeof parsed === "object" && parsed !== null
      ? (parsed as ApiPayload)
      : { detail: String(parsed) };
  } catch {
    // Reverse proxies may return a plain-text error such as "Internal Server
    // Error". Surface that message instead of throwing a misleading JSON error.
    return {
      detail: rawBody.trim().slice(0, 500) || `HTTP ${response.status}`,
    };
  }
};

export default function MLStudioPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [experiments, setExperiments] = useState<ExperimentInfo[]>([]);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [target, setTarget] = useState("");
  const [task, setTask] = useState<Task>("classification");
  const [metric, setMetric] = useState("AUTO");
  const [timeBudget, setTimeBudget] = useState("300");
  const [maxModels, setMaxModels] = useState("");
  const [maxRuntimePerModel, setMaxRuntimePerModel] = useState("");
  const [balanceClasses, setBalanceClasses] = useState(false);
  const [limitAlgorithms, setLimitAlgorithms] = useState(false);
  const [includeAlgos, setIncludeAlgos] = useState<H2OAlgorithm[]>(defaultAlgorithms);
  const [distribution, setDistribution] = useState("AUTO");
  const [stoppingMetric, setStoppingMetric] = useState("AUTO");
  const [targetEncoding, setTargetEncoding] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [predictingId, setPredictingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId),
    [datasets, datasetId]
  );

  const fetchDatasets = useCallback(async () => {
    const response = await fetch(
      buildApiUrlWithParams(API_URLS.ML_DATASETS, { session_id: sessionId })
    );
    const payload = await readApiResponse(response);
    if (!response.ok) {
      throw new Error(payload.detail || "Không tải được danh sách dataset.");
    }
    const nextDatasets = (payload.datasets || []) as DatasetInfo[];
    setDatasets(nextDatasets);
    setDatasetId((current) =>
      nextDatasets.some((item) => item.id === current) ? current : nextDatasets[0]?.id || ""
    );
  }, []);

  const fetchExperiments = useCallback(async () => {
    const response = await fetch(
      buildApiUrlWithParams(API_URLS.ML_EXPERIMENTS, { session_id: sessionId })
    );
    const payload = await readApiResponse(response);
    if (!response.ok) throw new Error(payload.detail || "Không tải được experiments.");
    setExperiments(payload.experiments || []);
  }, []);

  const fetchHealth = useCallback(async (connect = false) => {
    const response = await fetch(
      buildApiUrlWithParams(API_URLS.ML_HEALTH, { connect })
    );
    const payload = await readApiResponse(response);
    if (!response.ok) throw new Error(payload.detail || "Không kiểm tra được H2O runtime.");
    setHealth(payload as unknown as HealthInfo);
  }, []);

  const refresh = useCallback(async () => {
    try {
      await Promise.all([fetchDatasets(), fetchExperiments(), fetchHealth(false)]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không kết nối được backend.");
    }
  }, [fetchDatasets, fetchExperiments, fetchHealth]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const hasActiveRun = experiments.some((run) => run.status === "queued" || run.status === "running");
    if (!hasActiveRun) return;
    const interval = window.setInterval(() => {
      fetchExperiments().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(interval);
  }, [experiments, fetchExperiments]);

  useEffect(() => {
    if (!selectedDataset?.columns.includes(target)) {
      setTarget("");
    }
  }, [selectedDataset, target]);

  useEffect(() => {
    setMetric("AUTO");
    setDistribution("AUTO");
    setStoppingMetric("AUTO");
  }, [task]);

  const toggleAlgorithm = (algorithm: H2OAlgorithm, checked: boolean) => {
    setIncludeAlgos((current) =>
      checked
        ? current.includes(algorithm) ? current : [...current, algorithm]
        : current.filter((item) => item !== algorithm)
    );
  };

  const startExperiment = async () => {
    if (!datasetId || !target) {
      toast.error("Hãy chọn dataset và target column.");
      return;
    }
    if (limitAlgorithms && includeAlgos.length === 0) {
      toast.error("Hãy chọn ít nhất một thuật toán hoặc tắt giới hạn thuật toán.");
      return;
    }
    if (
      limitAlgorithms &&
      includeAlgos.length === 1 &&
      includeAlgos[0] === "StackedEnsemble"
    ) {
      toast.error("Stacked Ensemble cần ít nhất một thuật toán nền.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch(API_URLS.ML_EXPERIMENTS, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          dataset_id: datasetId,
          target,
          task,
          metric,
          time_budget: Number(timeBudget),
          max_models: maxModels ? Number(maxModels) : null,
          nfolds: 5,
          train_ratio: 0.7,
          validation_ratio: 0.15,
          seed: 42,
          balance_classes: task === "classification" && balanceClasses,
          include_algos: limitAlgorithms ? includeAlgos : [],
          distribution,
          stopping_metric: stoppingMetric,
          max_runtime_per_model: maxRuntimePerModel ? Number(maxRuntimePerModel) : null,
          preprocessing: targetEncoding ? ["target_encoding"] : [],
        }),
      });
      const payload = await readApiResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Không tạo được experiment.");
      toast.success(`Đã đưa experiment ${payload.id} vào hàng đợi.`);
      await fetchExperiments();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Không tạo được experiment.");
    } finally {
      setSubmitting(false);
    }
  };

  const uploadDataset = async (files: FileList | null) => {
    if (!files?.length) return;
    const formData = new FormData();
    Array.from(files).forEach((file) => formData.append("files", file));
    setUploading(true);
    try {
      const response = await fetch(
        buildApiUrlWithParams(API_URLS.ML_DATASET_UPLOAD, { session_id: sessionId }),
        { method: "POST", body: formData }
      );
      const payload = await readApiResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Upload thất bại.");
      toast.success("Dataset đã được upload vào workspace.");
      await fetchDatasets();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Upload thất bại.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const connectH2O = async () => {
    try {
      await fetchHealth(true);
      toast.success("Đã kiểm tra H2O runtime.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Không kết nối được H2O.");
    }
  };

  const predictDataset = async (experimentId: string) => {
    if (!datasetId) {
      toast.error("Hãy chọn dataset dùng để predict.");
      return;
    }
    setPredictingId(experimentId);
    try {
      const response = await fetch(`${API_URLS.ML_EXPERIMENTS}/${experimentId}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, dataset_id: datasetId }),
      });
      const payload = await readApiResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Predict thất bại.");
      toast.success(`Đã tạo ${payload.rows} predictions.`);
      window.location.href = payload.download_url;
      await fetchExperiments();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Predict thất bại.");
    } finally {
      setPredictingId(null);
    }
  };

  return (
    <main className="min-h-screen bg-muted/30 px-4 py-8 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Activity className="h-6 w-6 text-cyan-600" />
              <h1 className="text-2xl font-semibold">H2O ML Studio</h1>
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Train AutoML cho tabular classification/regression, đánh giá trên test set độc lập
              và tải model để tái sử dụng.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={health?.connected ? "default" : "secondary"}>
              {health?.connected
                ? `H2O ${health.version || "ready"}`
                : health?.installed
                  ? "H2O chưa kết nối"
                  : "H2O chưa sẵn sàng"}
            </Badge>
            <Button variant="outline" size="sm" onClick={connectH2O}>
              <RefreshCw className="mr-2 h-4 w-4" /> Kiểm tra runtime
            </Button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4" /> {error}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="h-4 w-4" /> Experiment mới
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium">Dataset</label>
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    accept=".csv,.tsv,.parquet,.xlsx,.xls"
                    onChange={(event) => uploadDataset(event.target.files)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {uploading ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Upload className="mr-1 h-3.5 w-3.5" />}
                    Upload
                  </Button>
                </div>
                <Select value={datasetId} onValueChange={setDatasetId}>
                  <SelectTrigger><SelectValue placeholder="Chọn dataset" /></SelectTrigger>
                  <SelectContent>
                    {datasets.map((dataset) => (
                      <SelectItem key={dataset.id} value={dataset.id}>
                        {dataset.name} · {formatBytes(dataset.size)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {datasets.length === 0 && (
                  <p className="text-xs text-muted-foreground">Chưa có tabular dataset trong workspace.</p>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Target column</label>
                <Select value={target} onValueChange={setTarget} disabled={!selectedDataset}>
                  <SelectTrigger><SelectValue placeholder="Chọn cột cần dự đoán" /></SelectTrigger>
                  <SelectContent>
                    {(selectedDataset?.columns || []).map((column) => (
                      <SelectItem key={column} value={column}>
                        {column} <span className="text-muted-foreground">({selectedDataset?.dtypes[column] || "unknown"})</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Task</label>
                  <Select value={task} onValueChange={(value) => setTask(value as Task)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="classification">Classification</SelectItem>
                      <SelectItem value="regression">Regression</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Sort metric</label>
                  <Select value={metric} onValueChange={setMetric}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="AUTO">Auto</SelectItem>
                      {task === "classification" ? (
                        <>
                          <SelectItem value="AUC">AUC</SelectItem>
                          <SelectItem value="AUCPR">AUCPR</SelectItem>
                          <SelectItem value="logloss">Logloss</SelectItem>
                          <SelectItem value="mean_per_class_error">Mean class error</SelectItem>
                        </>
                      ) : (
                        <>
                          <SelectItem value="RMSE">RMSE</SelectItem>
                          <SelectItem value="MAE">MAE</SelectItem>
                          <SelectItem value="RMSLE">RMSLE</SelectItem>
                        </>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Time budget (giây)</label>
                  <Input type="number" min={10} max={86400} value={timeBudget} onChange={(event) => setTimeBudget(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max models</label>
                  <Input type="number" min={1} placeholder="Không giới hạn" value={maxModels} onChange={(event) => setMaxModels(event.target.value)} />
                </div>
              </div>

              <details className="rounded-lg border bg-muted/20">
                <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium">
                  Advanced H2O options
                </summary>
                <div className="space-y-4 border-t p-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Distribution</label>
                    <Select value={distribution} onValueChange={setDistribution}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="AUTO">Auto</SelectItem>
                        {task === "classification" ? (
                          <>
                            <SelectItem value="bernoulli">Bernoulli (binary)</SelectItem>
                            <SelectItem value="multinomial">Multinomial</SelectItem>
                          </>
                        ) : (
                          <>
                            <SelectItem value="gaussian">Gaussian</SelectItem>
                            <SelectItem value="huber">Huber</SelectItem>
                            <SelectItem value="laplace">Laplace</SelectItem>
                            <SelectItem value="quantile">Quantile</SelectItem>
                            <SelectItem value="poisson">Poisson</SelectItem>
                            <SelectItem value="gamma">Gamma</SelectItem>
                            <SelectItem value="tweedie">Tweedie</SelectItem>
                          </>
                        )}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      Auto là lựa chọn an toàn. Poisson, Gamma và Tweedie yêu cầu target không âm.
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Stopping metric</label>
                      <Select value={stoppingMetric} onValueChange={setStoppingMetric}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="AUTO">Auto</SelectItem>
                          {task === "classification" ? (
                            <>
                              <SelectItem value="logloss">Logloss</SelectItem>
                              <SelectItem value="AUC">AUC</SelectItem>
                              <SelectItem value="AUCPR">AUCPR</SelectItem>
                              <SelectItem value="mean_per_class_error">Mean class error</SelectItem>
                              <SelectItem value="misclassification">Misclassification</SelectItem>
                            </>
                          ) : (
                            <>
                              <SelectItem value="deviance">Deviance</SelectItem>
                              <SelectItem value="RMSE">RMSE</SelectItem>
                              <SelectItem value="MSE">MSE</SelectItem>
                              <SelectItem value="MAE">MAE</SelectItem>
                              <SelectItem value="RMSLE">RMSLE</SelectItem>
                              <SelectItem value="R2">R²</SelectItem>
                            </>
                          )}
                        </SelectContent>
                      </Select>
                      <p className="text-[11px] text-muted-foreground">RMSLE không dùng được khi target có số âm.</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Max giây/model</label>
                      <Input
                        type="number"
                        min={1}
                        max={86400}
                        placeholder="Không giới hạn"
                        value={maxRuntimePerModel}
                        onChange={(event) => setMaxRuntimePerModel(event.target.value)}
                      />
                    </div>
                  </div>

                  <div className="space-y-3 rounded-md border bg-background p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium">Giới hạn thuật toán</p>
                        <p className="text-xs text-muted-foreground">Tắt để H2O tự dùng mọi thuật toán khả dụng.</p>
                      </div>
                      <Switch checked={limitAlgorithms} onCheckedChange={setLimitAlgorithms} />
                    </div>
                    {limitAlgorithms && (
                      <div className="grid grid-cols-2 gap-2">
                        {h2oAlgorithms.map(({ value, label }) => (
                          <label key={value} className="flex cursor-pointer items-center gap-2 text-xs">
                            <Checkbox
                              checked={includeAlgos.includes(value)}
                              onCheckedChange={(checked) => toggleAlgorithm(value, Boolean(checked))}
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-3">
                    <div>
                      <p className="text-sm font-medium">Target encoding</p>
                      <p className="text-xs text-muted-foreground">Preprocessing native của H2O, hiện còn experimental.</p>
                    </div>
                    <Switch checked={targetEncoding} onCheckedChange={setTargetEncoding} />
                  </div>
                </div>
              </details>

              {task === "classification" && (
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <p className="text-sm font-medium">Balance classes</p>
                    <p className="text-xs text-muted-foreground">Bật khi target mất cân bằng rõ rệt.</p>
                  </div>
                  <Switch checked={balanceClasses} onCheckedChange={setBalanceClasses} />
                </div>
              )}

              <Button className="w-full" disabled={submitting || !target} onClick={startExperiment}>
                {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                Train với H2O AutoML
              </Button>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Mặc định: 70% train, 15% validation, 15% final test và 5-fold CV. Final test không được dùng để chọn model.
              </p>
            </CardContent>
          </Card>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Experiments</h2>
              <Button variant="ghost" size="sm" onClick={refresh}>
                <RefreshCw className="mr-2 h-4 w-4" /> Refresh
              </Button>
            </div>
            {experiments.length === 0 && (
              <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">Chưa có experiment nào.</CardContent></Card>
            )}
            {experiments.map((run) => (
              <ExperimentCard
                key={run.id}
                run={run}
                canPredict={Boolean(datasetId)}
                predicting={predictingId === run.id}
                onPredict={() => predictDataset(run.id)}
              />
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}

function ExperimentCard({
  run,
  canPredict,
  predicting,
  onPredict,
}: {
  run: ExperimentInfo;
  canPredict: boolean;
  predicting: boolean;
  onPredict: () => void;
}) {
  const [expanded, setExpanded] = useState(run.status === "completed");
  const isActive = run.status === "queued" || run.status === "running";
  const leaderboard = run.result?.leaderboard || [];
  const leaderboardColumns = leaderboard.length ? Object.keys(leaderboard[0]) : [];
  const importance = run.result?.variable_importance || [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              {isActive && <Loader2 className="h-4 w-4 animate-spin text-cyan-600" />}
              {run.status === "completed" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
              {run.status === "failed" && <AlertCircle className="h-4 w-4 text-destructive" />}
              {run.dataset_name}
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              #{run.id} · target: {run.config.target} · {run.config.task} · {run.config.time_budget}s
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {run.config.include_algos?.length
                ? run.config.include_algos.join(", ")
                : "All available algorithms"}
              {run.config.distribution && run.config.distribution !== "AUTO"
                ? ` · ${run.config.distribution}`
                : ""}
              {run.config.stopping_metric && run.config.stopping_metric !== "AUTO"
                ? ` · stop: ${run.config.stopping_metric}`
                : ""}
              {run.config.preprocessing?.includes("target_encoding")
                ? " · target encoding"
                : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={run.status === "failed" ? "destructive" : run.status === "completed" ? "default" : "secondary"}>
              {run.status}
            </Badge>
            {run.status === "completed" && (
              <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>
                {expanded ? "Thu gọn" : "Xem kết quả"}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      {run.error && <CardContent className="pt-0 text-sm text-destructive">{run.error}</CardContent>}
      {expanded && run.result && (
        <CardContent className="space-y-5 border-t pt-4">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Final test metrics</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(run.result.metrics).map(([name, value]) => (
                <div key={name} className="rounded-lg border bg-muted/30 px-3 py-2">
                  <p className="text-[11px] uppercase text-muted-foreground">{name}</p>
                  <p className="font-mono text-sm font-medium">{formatMetric(value)}</p>
                </div>
              ))}
            </div>
          </div>

          {leaderboard.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Leaderboard</p>
              <div className="max-h-72 overflow-auto rounded-lg border">
                <Table>
                  <TableHeader><TableRow>{leaderboardColumns.map((column) => <TableHead key={column} className="whitespace-nowrap text-xs">{column}</TableHead>)}</TableRow></TableHeader>
                  <TableBody>
                    {leaderboard.slice(0, 20).map((row, index) => (
                      <TableRow key={index}>{leaderboardColumns.map((column) => <TableCell key={column} className="whitespace-nowrap font-mono text-xs">{formatMetric(row[column])}</TableCell>)}</TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          {importance.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Feature importance</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {importance.slice(0, 12).map((row, index) => {
                  const feature = String(row.variable ?? row.feature ?? `feature ${index + 1}`);
                  const raw = row.percentage ?? row.scaled_importance ?? row.relative_importance;
                  const percentage = typeof raw === "number" ? Math.max(0, Math.min(1, raw)) : 0;
                  return (
                    <div key={`${feature}-${index}`} className="space-y-1">
                      <div className="flex justify-between gap-3 text-xs">
                        <span className="truncate" title={feature}>{feature}</span>
                        <span className="font-mono text-muted-foreground">{(percentage * 100).toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-cyan-600" style={{ width: `${percentage * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="default" size="sm" disabled={!canPredict || predicting} onClick={onPredict}>
              {predicting ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-2 h-3.5 w-3.5" />}
              Predict dataset đang chọn
            </Button>
            {Object.entries(run.result.artifacts).map(([name, artifact]) => (
              <Button key={name} variant="outline" size="sm" asChild>
                <a href={artifact.download_url}>
                  <Download className="mr-2 h-3.5 w-3.5" /> {artifactLabel[name] || name}
                </a>
              </Button>
            ))}
            <span className="text-xs text-muted-foreground">
              Split: {run.result.row_counts.train} / {run.result.row_counts.validation} / {run.result.row_counts.test}
            </span>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
