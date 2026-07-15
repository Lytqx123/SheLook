"use client";

import { useState } from "react";
import {
  Card, Form, Input, Select, InputNumber, Button, Tag,
  Descriptions, Alert, Spin, App, Row, Col, Statistic,
} from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { useGenerateVideo, useVideoProviders } from "@/hooks";
import { VIDEO_STYLE_OPTIONS, VIDEO_RESOLUTION_OPTIONS } from "@/constants";
import type { VideoGenerateResponse, VideoProvider } from "@/types";
import PageHeader from "@/components/PageHeader";

const { TextArea } = Input;

export default function VideoGenerateContent() {
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const [result, setResult] = useState<VideoGenerateResponse | null>(null);

  const generateVideo = useGenerateVideo();
  const { data: providersData } = useVideoProviders();
  const providers = providersData?.providers || [];
  const canGenerate = providers.some((provider) => provider.status === "configured");

  const handleGenerate = async (values: {
    image_url: string;
    prompt?: string;
    duration?: number;
    resolution?: string;
    style?: string;
  }) => {
    message.loading({ content: "正在提交视频生成任务...", key: "video" });
    try {
      const res = await generateVideo.mutateAsync({
        image_url: values.image_url,
        prompt: values.prompt,
        duration: values.duration,
        resolution: values.resolution,
        style: values.style,
      });
      setResult(res);
      if (res.status === "completed") {
        message.success({ content: `视频生成完成 (${res.provider})`, key: "video" });
      } else {
        message.warning({ content: res.message || `视频生成未成功 (${res.provider})`, key: "video" });
      }
    } catch (error: unknown) {
      message.error({
        content: error instanceof Error ? error.message : "视频生成失败",
        key: "video",
      });
    }
  };

  const statusColor = result?.status === "completed" ? "green" :
    result?.status === "failed" ? "red" :
    result?.status === "pending" ? "orange" : "default";

  const statusLabel = result?.status === "completed" ? "完成" :
    result?.status === "failed" ? "失败" :
    result?.status === "pending" ? "超时" : result?.status || "—";

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="AI 视频生成"
        subtitle="将商品图片转化为动态展示视频（Kling AI 3.0 / Runway Gen-4.5）"
      />

      {/* 生成表单 */}
      <Card title="生成参数" style={{ marginBottom: 20 }}>
        <Form form={form} layout="vertical" onFinish={handleGenerate}>
          <Row gutter={[20, 20]}>
            <Col xs={24} md={12}>
              <Form.Item
                label="商品图片 URL"
                name="image_url"
                rules={[{ required: true, message: "请输入商品图片地址" }]}
                help="输入已生成的商品图 URL（MinIO 或 CDN 地址）"
              >
                <Input placeholder="https://minio:9000/product-images/xxx.jpg" />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="视频风格" name="style" initialValue="product_showcase">
                <Select options={[...VIDEO_STYLE_OPTIONS]} />
              </Form.Item>
            </Col>
            <Col xs={6} md={3}>
              <Form.Item label="时长(秒)" name="duration" initialValue={10}>
                <InputNumber min={5} max={120} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={6} md={3}>
              <Form.Item label="分辨率" name="resolution" initialValue="1080p">
                <Select options={[...VIDEO_RESOLUTION_OPTIONS]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="自定义 Prompt（可选）" name="prompt" help="用自然语言描述期望的视频效果">
            <TextArea rows={2} placeholder="如：模特穿着连衣裙在巴黎街头自然行走，柔光，慢动作" />
          </Form.Item>
          {providersData && !canGenerate && (
            <Alert
              type="warning"
              showIcon
              title="当前未配置可用的视频生成提供商；请先配置 Kling 或 Runway API 凭据。"
              style={{ marginBottom: 16 }}
            />
          )}
          <Button
            type="primary"
            size="large"
            htmlType="submit"
            loading={generateVideo.isPending}
            disabled={!canGenerate}
            icon={<PlayCircleOutlined />}
          >
            生成视频
          </Button>
        </Form>
      </Card>

      {/* 生成结果 */}
      {result && (
        <Card title="生成结果" style={{ marginBottom: 20 }}>
          <Row gutter={[20, 20]}>
            <Col span={8}>
              <Statistic title="模型" value={result.model} />
            </Col>
            <Col span={8}>
              <Statistic title="提供商" value={result.provider} />
            </Col>
            <Col span={8}>
              <Statistic
                title="状态"
                value={statusLabel}
                styles={{
                  content: {
                    color: statusColor === "green" ? "#059669" :
                           statusColor === "red" ? "#DC2626" :
                           statusColor === "orange" ? "#d48806" : "#2563EB"
                  },
                }}
              />
            </Col>
          </Row>
          {result.video_url && (
            <div className="mt-4">
              <p className="text-sm font-medium mb-2">视频链接</p>
              <a
                href={result.video_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-500 underline text-sm break-all"
              >
                {result.video_url}
              </a>
            </div>
          )}
          {result.message && (
            <Alert type="info" title={result.message} className="mt-3" />
          )}
        </Card>
      )}

      {/* 提供商信息 */}
      <Card title="可用视频生成提供商" size="small">
        {providers.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {providers.map((p: VideoProvider) => (
              <Card key={p.name} size="small" className="border-gray-100">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">{p.name}</span>
                  <Tag color={p.status === "configured" ? "green" : "red"}>
                    {p.status === "configured" ? "已配置" : p.status}
                  </Tag>
                </div>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="类型">{p.type}</Descriptions.Item>
                  <Descriptions.Item label="费用">{p.cost_per_second}</Descriptions.Item>
                  <Descriptions.Item label="最大时长">{p.max_duration}</Descriptions.Item>
                  <Descriptions.Item label="最大分辨率">{p.max_resolution}</Descriptions.Item>
                  <Descriptions.Item label="优势">
                    {p.strengths?.length ? p.strengths.join("、") : "—"}
                  </Descriptions.Item>
                  {p.note && (
                    <Descriptions.Item label="备注">
                      <span className="text-gray-500">{p.note}</span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </Card>
            ))}
          </div>
        ) : (
          <Spin description="加载提供商信息..." />
        )}
      </Card>
    </div>
  );
}
