"use client";

import React, { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users, AlertTriangle, Coins } from "lucide-react";

export interface ProfileAttributes {
  high_spender_pct?: number;
  avg_fee?: number;
  tier_upgrade_rate?: number;
  tier_downgrade_rate?: number;
  usage_decline_strong_pct?: number;
  usage_decline_mild_pct?: number;
  usage_unstable_pct?: number;
  status_worsening_pct?: number;
  loyalty_rank_avg?: number;
  csat_avg?: number;
  ces_avg?: number;
  package_composition?: Record<string, number>;
}

export interface Persona {
  cluster_id: number;
  persona_name: string;
  support: number;
  support_pct: number;
  arpu: number;
  churn_rate: number;
  confidence: string;
  sample_persona_text: string;
  severity?: string;
  risk?: string;
  risk_tier?: string;
  profile_attributes?: ProfileAttributes;
  recommended_actions?: string[];
}

interface PersonaDashboardProps {
  data: Persona[];
}

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8", "#82ca9d"];

export function PersonaDashboard({ data }: PersonaDashboardProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "churn" | "revenue">("overview");

  let actualData = data;
  if (data && !Array.isArray(data) && Array.isArray((data as any).personas)) {
    actualData = (data as any).personas;
  }

  if (!actualData || !Array.isArray(actualData)) {
    return (
      <div className="p-4 border border-yellow-500 rounded text-yellow-700 bg-yellow-50 text-sm">
        Waiting for valid Persona JSON data format...
      </div>
    );
  }

  // Calculate Revenue at Risk
  const chartData = actualData.map((item) => ({
    ...item,
    total_revenue: item.support * item.arpu,
    revenue_at_risk: item.support * item.arpu * item.churn_rate,
    // Add C{id} prefix to guarantee unique keys for Recharts, preventing duplicate X-Axis labels from overwriting each other
    short_name: `C${item.cluster_id}: ${item.persona_name.length > 12 ? item.persona_name.substring(0, 12) + "..." : item.persona_name}`,
  }));

  const totalSupport = actualData.reduce((acc, curr) => acc + curr.support, 0);
  const totalRevenueAtRisk = chartData.reduce((acc, curr) => acc + curr.revenue_at_risk, 0);
  const avgChurn = actualData.reduce((acc, curr) => acc + curr.churn_rate * curr.support, 0) / (totalSupport || 1);

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(value);
  };

  const formatPercent = (value: number) => {
    return (value * 100).toFixed(1) + "%";
  };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-700 rounded-md shadow-md text-xs z-50">
          <p className="font-bold mb-1 text-gray-900 dark:text-gray-100">{label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} style={{ color: entry.color }} className="my-1">
              {entry.name}: {entry.name.includes("Revenue") || entry.name.includes("ARPU")
                ? formatCurrency(entry.value)
                : entry.name.includes("Churn") || entry.name.includes("Rate")
                  ? formatPercent(entry.value)
                  : entry.value}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="w-full my-6 space-y-4 font-sans">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Customers</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalSupport.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">Clustered in {data.length} personas</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Churn Rate</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatPercent(avgChurn)}</div>
            <p className="text-xs text-muted-foreground">Weighted average</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Revenue at Risk</CardTitle>
            <Coins className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-500">{formatCurrency(totalRevenueAtRisk)}</div>
            <p className="text-xs text-muted-foreground">Monthly estimated</p>
          </CardContent>
        </Card>
      </div>

      <Card className="w-full">
        <CardHeader>
          <CardTitle>Dynamic Persona Analysis</CardTitle>
          <CardDescription>Interactive visualizations of the generated personas</CardDescription>
          <div className="flex space-x-2 mt-4">
            <Badge
              variant={activeTab === "overview" ? "default" : "outline"}
              className="cursor-pointer"
              onClick={() => setActiveTab("overview")}
            >
              Population Overview
            </Badge>
            <Badge
              variant={activeTab === "churn" ? "default" : "outline"}
              className="cursor-pointer"
              onClick={() => setActiveTab("churn")}
            >
              Churn Risk (Radar)
            </Badge>
            <Badge
              variant={activeTab === "revenue" ? "default" : "outline"}
              className="cursor-pointer"
              onClick={() => setActiveTab("revenue")}
            >
              Revenue at Risk
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-80 w-full mt-4">
            {activeTab === "overview" && (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis
                    dataKey="short_name"
                    angle={-45}
                    textAnchor="end"
                    height={70}
                    tick={{ fontSize: 11 }}
                  />
                  <YAxis />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend verticalAlign="top" />
                  <Bar dataKey="support" name="Customer Count" fill="#8884d8" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}

            {activeTab === "churn" && (
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart cx="50%" cy="50%" outerRadius="80%" data={chartData}>
                  <PolarGrid opacity={0.3} />
                  <PolarAngleAxis dataKey="short_name" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 1]} tickFormatter={formatPercent} />
                  <Radar name="Churn Rate" dataKey="churn_rate" stroke="#ff4d4f" fill="#ff4d4f" fillOpacity={0.6} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend />
                </RadarChart>
              </ResponsiveContainer>
            )}

            {activeTab === "revenue" && (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis
                    dataKey="short_name"
                    angle={-45}
                    textAnchor="end"
                    height={70}
                    tick={{ fontSize: 11 }}
                  />
                  <YAxis tickFormatter={(val) => `${(val / 1000000).toFixed(0)}M`} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend verticalAlign="top" />
                  <Bar dataKey="total_revenue" name="Safe Revenue" stackId="a" fill="#10b981" />
                  <Bar dataKey="revenue_at_risk" name="Revenue at Risk" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
