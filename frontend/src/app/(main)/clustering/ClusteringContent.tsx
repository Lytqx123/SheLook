"use client";

import { useState } from "react";
import {
  Card, Select, Button, Tag, Statistic, Row, Col, Table,
  Spin, Empty, Alert, App,
} from "antd";
import { ClusterOutlined, BulbOutlined } from "@ant-design/icons";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";
import { useRunClustering } from "@/hooks";
import {
  MARKET_OPTIONS_SELECT, CATEGORY_OPTIONS_SELECT,
  CLUSTERING_ALGORITHM_OPTIONS,
} from "@/constants";
import type { ClusteringRunResponse, ClusterInfo, TSNECoordinate } from "@/types";
import PageHeader from "@/components/PageHeader";

const CLUSTER_COLORS = [
  "#2563EB", "#059669", "#fa8c16", "#722ed1", "#eb2f96",
  "#13c2c2", "#f5222d", "#2f54eb", "#D97706", "#a0d911",
];

export default function ClusteringContent() {
  const [algorithm, setAlgorithm] = useState<string>("kmeans");
  const [category, setCategory] = useState<string | undefined>();
  const [market, setMarket] = useState<string | undefined>();
  const [result, setResult] = useState<ClusteringRunResponse | null>(null);

  const runClustering = useRunClustering();
  const { message } = App.useApp();

  const handleRun = async () => {
    message.loading({ content: "正在执行聚类分析...", key: "cluster" });
    try {
      const res = await runClustering.mutateAsync({
        category, market,
        algorithm: algorithm as "kmeans" | "hdbscan",
      });
      setResult(res);
      message.success({
        content: `聚类完成：${res.n_clusters} 个簇，轮廓系数 ${res.silhouette_score != null ? res.silhouette_score.toFixed(3) : "N/A"}`,
        key: "cluster",
      });
    } catch {
      message.error({ content: "聚类分析失败", key: "cluster" });
    }
  };

  // t-SNE scatter data grouped by cluster
  const scatterData = (result?.tsne_coordinates || []).map((p: TSNECoordinate) => ({
    x: p.x, y: p.y, cluster: p.cluster_id, product: p.product_id,
  }));

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="聚类分析"
        subtitle="基于 CLIP 向量对商品图进行视觉聚类，发现高/低 CTR 风格群"
      />

      {/* 控制面板 */}
      <Card title="聚类参数" style={{ marginBottom: 20 }}>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="text-sm mb-1 text-gray-500">算法</p>
            <Select
              value={algorithm}
              onChange={setAlgorithm}
              style={{ width: 200 }}
              options={[...CLUSTERING_ALGORITHM_OPTIONS]}
            />
          </div>
          <div>
            <p className="text-sm mb-1 text-gray-500">品类（可选）</p>
            <Select
              allowClear
              placeholder="全部品类"
              value={category}
              onChange={setCategory}
              style={{ width: 150 }}
              options={CATEGORY_OPTIONS_SELECT}
            />
          </div>
          <div>
            <p className="text-sm mb-1 text-gray-500">市场（可选）</p>
            <Select
              allowClear
              placeholder="全部市场"
              value={market}
              onChange={setMarket}
              style={{ width: 150 }}
              options={MARKET_OPTIONS_SELECT}
            />
          </div>
          <Button
            type="primary"
            icon={<ClusterOutlined />}
            onClick={handleRun}
            loading={runClustering.isPending}
            size="large"
          >
            执行聚类
          </Button>
        </div>
      </Card>

      {/* 结果区 */}
      {runClustering.isPending && (
        <div className="flex items-center justify-center" style={{ padding: "120px 0", marginBottom: 20 }}>
          <Spin size="large" description="聚类计算中（可能需要几秒钟）..." />
        </div>
      )}

      {result && (
        <>
          {/* 概览指标 */}
          <Row gutter={[20, 20]} style={{ marginBottom: 20 }}>
            <Col xs={12} lg={6}>
              <Card>
                <Statistic title="算法" value={result.algorithm.toUpperCase()} />
              </Card>
            </Col>
            <Col xs={12} lg={6}>
              <Card>
                <Statistic title="簇数量" value={result.n_clusters} />
              </Card>
            </Col>
            <Col xs={12} lg={6}>
              <Card>
                <Statistic
                  title="轮廓系数"
                  value={result.silhouette_score != null ? result.silhouette_score.toFixed(3) : "N/A"}
                  styles={{
                    content: {
                      color: (result.silhouette_score ?? 0) > 0.3 ? "#059669" : "#D97706",
                    },
                  }}
                />
              </Card>
            </Col>
            <Col xs={12} lg={6}>
              <Card>
                <Statistic
                  title="样本数"
                  value={result.tsne_coordinates.length}
                />
              </Card>
            </Col>
          </Row>

          {/* t-SNE 可视化 */}
          <Card title="t-SNE 降维可视化" style={{ marginBottom: 20 }}>
            {scatterData.length > 0 ? (
              <ResponsiveContainer width="100%" height={450}>
                <ScatterChart>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                  <XAxis type="number" dataKey="x" tick={false} />
                  <YAxis type="number" dataKey="y" tick={false} />
                  <Tooltip
                    formatter={(_, _name, props) => [
                      `商品 ${props.payload.product}`,
                      `簇 ${props.payload.cluster}`,
                    ]}
                  />
                  {Array.from(new Set(scatterData.map((d: {cluster: number}) => d.cluster))).map((clusterId) => (
                    <Scatter
                      key={clusterId}
                      name={`簇 ${clusterId}`}
                      data={scatterData.filter((d: {cluster: number}) => d.cluster === clusterId)}
                      fill={CLUSTER_COLORS[clusterId % CLUSTER_COLORS.length]}
                      opacity={0.6}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            ) : (
              <Empty description="无 t-SNE 坐标数据" />
            )}
          </Card>

          {/* 聚类详情表 */}
          <Card title="各簇统计" style={{ marginBottom: 20 }}>
            <Table
              dataSource={(result.clusters || []).map((c: ClusterInfo) => ({
                key: c.cluster_id, ...c,
              }))}
              columns={[
                { title: "簇 ID", dataIndex: "cluster_id", key: "id" },
                { title: "样本数", dataIndex: "size", key: "size",
                  sorter: (a: ClusterInfo, b: ClusterInfo) => a.size - b.size },
                {
                  title: "平均 CTR", dataIndex: "avg_ctr", key: "ctr",
                  render: (v: number | undefined) =>
                    v != null ? (
                      <Tag color={v > 0.03 ? "green" : "orange"}>
                        {(v * 100).toFixed(2)}%
                      </Tag>
                    ) : "—",
                  sorter: (a: ClusterInfo, b: ClusterInfo) => (a.avg_ctr || 0) - (b.avg_ctr || 0),
                },
                {
                  title: "平均退货率", dataIndex: "avg_return_rate", key: "ret",
                  render: (v: number | undefined) =>
                    v != null ? `${(v * 100).toFixed(1)}%` : "—",
                },
                {
                  title: "主要品类", dataIndex: "top_categories", key: "cats",
                  render: (cats: string[] | undefined) =>
                    cats?.map((c) => <Tag key={c} className="text-xs">{c}</Tag>) || "—",
                },
                {
                  title: "标签", dataIndex: "label", key: "label",
                  render: (l: string | undefined) =>
                    l ? <Tag color="blue">{l}</Tag> : null,
                },
              ]}
              pagination={{ pageSize: 10 }}
              size="small"
            />
          </Card>
        </>
      )}

      {/* 空状态 */}
      {!result && !runClustering.isPending && (
        <Card className="text-center py-16">
          <BulbOutlined className="text-5xl text-gray-300 mb-4" />
          <p className="text-gray-400 text-lg mb-2">尚未执行聚类分析</p>
          <p className="text-gray-400 text-sm">
            选择算法和筛选条件后，点击"执行聚类"开始分析
          </p>
        </Card>
      )}
    </div>
  );
}
