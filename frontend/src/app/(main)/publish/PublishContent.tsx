"use client";

import { useState } from "react";
import { Steps, Button, App, Tag, Input, InputNumber, Select, Form, Card, Descriptions, Divider, Alert, Progress, Tooltip, Tabs, Upload, Empty, Image as AntImage } from "antd";
import { InboxOutlined, CheckCircleOutlined, CloseCircleOutlined, SafetyCertificateOutlined, BulbOutlined, FileSearchOutlined, SearchOutlined, PictureOutlined } from "@ant-design/icons";
import SchemeCard from "@/components/SchemeCard";
import GenerateProgress from "@/components/GenerateProgress";
import ComparisonViewer from "@/components/ComparisonViewer";
import QualityRadar from "@/components/QualityRadar";
import PageHeader from "@/components/PageHeader";
import {
  useCreateProduct,
  useRecommendSchemes,
  useRecommendSchemesFusion,
  useStartGeneration,
  useGenerationStatus,
  useSearchByImage,
  useSearchByImageUpload,
} from "@/hooks";
import { api } from "@/lib/api";
import type { SchemeOut, FusionDimension, ImageSearchResponse, ImageSearchResult } from "@/types";
import { L1_DIM_LABELS, L3_LABELS, CATEGORY_OPTIONS_SELECT, MARKET_OPTIONS_SELECT } from "@/constants";

// 三维度融合推荐 —— 中文标签和颜色
const FUSION_DIM_LABELS: Record<FusionDimension, string> = {
  same_category: "同品类最优",
  cross_category: "跨品类迁移",
  market: "市场本地化",
};

const FUSION_DIM_COLORS: Record<FusionDimension, string> = {
  same_category: "blue",
  cross_category: "purple",
  market: "orange",
};

export default function PublishContent() {
  const [step, setStep] = useState(0);
  const [productId, setProductId] = useState<number | null>(null);
  const [productImageUrl, setProductImageUrl] = useState<string>("");
  const [productCategory, setProductCategory] = useState<string>("");
  const [targetMarket, setTargetMarket] = useState<string>("us");
  const [selectedSchemes, setSelectedSchemes] = useState<SchemeOut[]>([]);
  const [taskImageIds, setTaskImageIds] = useState<number[]>([]);
  const [publishing, setPublishing] = useState(false);

  // 以图搜图
  const [searchImageUrl, setSearchImageUrl] = useState("");
  const [searchCategory, setSearchCategory] = useState<string | undefined>(undefined);
  const [searchMarket, setSearchMarket] = useState<string | undefined>(undefined);
  const [searchResults, setSearchResults] = useState<ImageSearchResponse | null>(null);

  // Mutations
  const createProduct = useCreateProduct();
  const recommendSchemes = useRecommendSchemes();
  const recommendFusion = useRecommendSchemesFusion();
  const startGeneration = useStartGeneration();
  const searchByImageMutation = useSearchByImage();
  const searchByImageUploadMutation = useSearchByImageUpload();
  const { message } = App.useApp();

  // 推荐方案（mutation data）
  const schemeData = recommendSchemes.data;
  const schemes: SchemeOut[] = schemeData?.schemes?.flatMap(
    (item) => item.schemes
  ) ?? [];

  // Step 0: 创建商品
  const handleCreateProduct = async (values: {
    title: string;
    category: string;
    sku_code: string;
    price_min: number;
    price_max: number;
    image_url: string;
    target_market: string;
  }) => {
    message.loading({ content: "正在创建商品...", key: "create" });
    try {
      const result = await createProduct.mutateAsync({
        sku_code: values.sku_code,
        title: values.title,
        category: values.category,
        price_range: `$${values.price_min}-${values.price_max}`,
        target_markets: [values.target_market],
      });
      setProductId(result.id);
      setProductImageUrl(values.image_url);
      setProductCategory(values.category);
      setTargetMarket(values.target_market);
      message.success({ content: `商品创建成功 (ID: ${result.id})`, key: "create" });
      setStep(1);

      // 同时触发两个推荐：CLIP 相似度检索 + 三维度融合推荐
      message.loading({ content: "正在分析推荐方案...", key: "schemes" });
      recommendSchemes.mutate(
        { imageUrl: values.image_url, topK: 5 },
        {
          onSuccess: () => message.success({ content: "CLIP 方案推荐完成", key: "schemes" }),
          onError: () => message.warning({ content: "CLIP 方案推荐失败，可手动选择", key: "schemes" }),
        }
      );
      recommendFusion.mutate(
        { category: values.category, market: values.target_market, top_k: 5 },
        {
          onError: () => message.warning({ content: "三维度融合推荐失败", key: "fusion" }),
        }
      );
    } catch {
      message.error({ content: "商品创建失败，请重试", key: "create" });
    }
  };

  // Step 1: 选择方案
  const handleToggleScheme = (scheme: SchemeOut) => {
    setSelectedSchemes((prev) => {
      const exists = prev.find((s) => s.id === scheme.id);
      if (exists) return prev.filter((s) => s.id !== scheme.id);
      if (prev.length >= 3) {
        message.warning("最多选择 3 套方案");
        return prev;
      }
      return [...prev, scheme];
    });
  };

  // 以图搜图
  const handleSearchByUrl = async () => {
    if (!searchImageUrl.trim()) { message.warning("请输入图片 URL"); return; }
    setSearchResults(null);
    message.loading({ content: "正在以图搜图...", key: "img-search" });
    try {
      const res = await searchByImageMutation.mutateAsync({
        image_url: searchImageUrl.trim(),
        top_k: 10,
        category: searchCategory,
        market: searchMarket,
      });
      setSearchResults(res);
      message.success({ content: `检索到 ${res.total} 个相似商品`, key: "img-search" });
    } catch (e: unknown) {
      message.error({ content: e instanceof Error ? e.message : "以图搜图失败", key: "img-search" });
    }
  };

  const handleSearchByUpload = async (file: File) => {
    setSearchResults(null);
    message.loading({ content: "正在以图搜图...", key: "img-search" });
    try {
      const res = await searchByImageUploadMutation.mutateAsync({
        file,
        topK: 10,
        category: searchCategory,
      });
      setSearchResults(res);
      message.success({ content: `检索到 ${res.total} 个相似商品`, key: "img-search" });
    } catch (e: unknown) {
      message.error({ content: e instanceof Error ? e.message : "以图搜图失败", key: "img-search" });
    }
    return false; // 阻止 antd Upload 自动上传
  };

  const handleStartGen = async () => {
    if (selectedSchemes.length === 0) return;
    message.loading({ content: `正在提交 ${selectedSchemes.length} 个生成任务...`, key: "generate" });

    try {
      const results = await Promise.allSettled(
        selectedSchemes.map((scheme) =>
          startGeneration.mutateAsync({
            scheme_id: scheme.id,
            market_variant: targetMarket,
          })
        )
      );
      const ids: number[] = [];
      let failCount = 0;
      results.forEach((r) => {
        if (r.status === "fulfilled") {
          ids.push(r.value.image_id);
        } else {
          failCount++;
        }
      });
      if (ids.length > 0) {
        setTaskImageIds(ids);
        if (failCount > 0) {
          message.warning({
            content: `${ids.length} 个任务已启动，${failCount} 个提交失败`,
            key: "generate",
          });
        } else {
          message.success({
            content: `${ids.length} 个生成任务已启动`,
            key: "generate",
          });
        }
        setStep(2);
      } else {
        message.error({ content: "所有生成任务提交失败，请重试", key: "generate" });
      }
    } catch {
      message.error({ content: "生成任务提交异常，请重试", key: "generate" });
    }
  };

  // 渲染
  return (
      <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
        <PageHeader title="发品工作台" subtitle="创建商品 → AI推荐方案 → 智能生成 → 质检出品" />

        {/* 步骤条 */}
        <Card>
          <Steps
            current={step}
            items={[
              { title: "创建商品" },
              { title: "AI 推荐方案" },
              { title: "智能生成" },
              { title: "质检与出品" },
            ]}
          />
        </Card>

        {/* Step 0: 创建商品表单 */}
        {step === 0 && (
          <>
          {/* 以图搜图 */}
          <Card
            title={
              <div className="flex items-center gap-2">
                <FileSearchOutlined style={{ color: "#2563EB" }} />
                <span className="font-semibold">以图搜图</span>
                <Tag color="blue" className="ml-1">CLIP + pgvector</Tag>
              </div>
            }
          >
            <p className="text-sm text-gray-500 mb-4">
              上传或输入图片 URL，基于 CLIP 视觉向量检索已有商品库中最相似的商品及其视觉方案，作为发品参考
            </p>
            <Tabs
              defaultActiveKey="url"
              items={[
                {
                  key: "url",
                  label: <span className="flex items-center gap-1"><SearchOutlined />URL 搜索</span>,
                  children: (
                    <div className="space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <Input
                          placeholder="https://cdn.example.com/product/flatlay.jpg"
                          value={searchImageUrl}
                          onChange={(e) => setSearchImageUrl(e.target.value)}
                          prefix={<PictureOutlined className="text-gray-400" />}
                        />
                        <Select
                          allowClear
                          placeholder="品类过滤（可选）"
                          options={CATEGORY_OPTIONS_SELECT}
                          value={searchCategory}
                          onChange={setSearchCategory}
                        />
                        <Select
                          allowClear
                          placeholder="市场过滤（可选）"
                          options={MARKET_OPTIONS_SELECT}
                          value={searchMarket}
                          onChange={setSearchMarket}
                        />
                      </div>
                      <Button
                        type="primary"
                        icon={<SearchOutlined />}
                        onClick={handleSearchByUrl}
                        loading={searchByImageMutation.isPending}
                      >
                        以图搜图
                      </Button>
                    </div>
                  ),
                },
                {
                  key: "upload",
                  label: <span className="flex items-center gap-1"><InboxOutlined />上传图片</span>,
                  children: (
                    <div className="space-y-3">
                      <Upload.Dragger
                        accept="image/*"
                        showUploadList={false}
                        beforeUpload={handleSearchByUpload}
                        disabled={searchByImageUploadMutation.isPending}
                      >
                        <p className="text-gray-400" style={{ fontSize: 36 }}>
                          <InboxOutlined />
                        </p>
                        <p className="text-gray-600 text-sm">
                          点击或拖拽图片到此处上传检索
                        </p>
                        <p className="text-xs text-gray-400 mt-1">
                          支持 JPG / PNG / WebP，单文件 ≤ 10MB
                        </p>
                      </Upload.Dragger>
                      <Select
                        allowClear
                        placeholder="品类过滤（可选）"
                        options={CATEGORY_OPTIONS_SELECT}
                        value={searchCategory}
                        onChange={setSearchCategory}
                        style={{ width: 220 }}
                      />
                    </div>
                  ),
                },
              ]}
            />

            {/* 搜索结果 */}
            {searchResults && (
              <div className="mt-4">
                <Divider className="my-3" />
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-medium text-gray-700">
                    相似商品检索结果
                  </span>
                  <Tag color="purple">{searchResults.source}</Tag>
                </div>
                {searchResults.results.length === 0 ? (
                  <Empty description="未找到相似商品" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {searchResults.results.map((item: ImageSearchResult) => (
                      <Card
                        key={item.product_id}
                        size="small"
                        className="hover:shadow-md transition-shadow"
                        title={
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium truncate">
                              {item.title || `商品 #${item.product_id}`}
                            </span>
                            <Tag color={
                              item.similarity >= 0.85 ? "green"
                                : item.similarity >= 0.7 ? "blue"
                                : "default"
                            }>
                              {(item.similarity * 100).toFixed(1)}%
                            </Tag>
                          </div>
                        }
                      >
                        <div className="flex gap-3">
                          <div className="w-20 h-20 rounded overflow-hidden bg-gray-100 flex items-center justify-center shrink-0">
                            {item.image_url ? (
                              <AntImage
                                src={item.image_url}
                                alt={item.title || `product-${item.product_id}`}
                                className="w-full h-full object-cover"
                                fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect fill='%23f5f5f5' width='80' height='80'/%3E%3Ctext x='40' y='44' text-anchor='middle' fill='%23999' font-size='12'%3E无图%3C/text%3E%3C/svg%3E"
                              />
                            ) : (
                              <PictureOutlined style={{ fontSize: 24, color: "#cbd5e1" }} />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-xs text-gray-500 space-y-1">
                              {item.category && (
                                <div className="flex items-center gap-1">
                                  <span className="text-gray-400">品类：</span>
                                  <Tag className="text-xs">{item.category}</Tag>
                                </div>
                              )}
                              <div className="flex items-center gap-1">
                                <span className="text-gray-400">商品 ID：</span>
                                <span className="font-mono">{item.product_id}</span>
                              </div>
                              {item.schemes && item.schemes.length > 0 && (
                                <div>
                                  <span className="text-gray-400">关联方案：</span>
                                  <span className="text-gray-600">{item.schemes.length} 套</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                        {item.schemes && item.schemes.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-gray-50 flex flex-wrap gap-1">
                            {item.schemes.slice(0, 3).map((sc) => (
                              <Tooltip key={sc.id} title={sc.recommendation_reason || sc.scheme_name}>
                                <Tag color="purple" className="text-xs cursor-default">
                                  {sc.scheme_name}
                                </Tag>
                              </Tooltip>
                            ))}
                            {item.schemes.length > 3 && (
                              <Tag className="text-xs">+{item.schemes.length - 3}</Tag>
                            )}
                          </div>
                        )}
                      </Card>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card title="创建新商品">
            <Form layout="vertical" onFinish={handleCreateProduct}>
              <div className="grid grid-cols-2 gap-4">
                <Form.Item
                  label="商品标题"
                  name="title"
                  rules={[{ required: true, message: "请输入商品标题" }]}
                >
                  <Input placeholder="如：夏季碎花连衣裙" />
                </Form.Item>
                <Form.Item
                  label="SKU 编码"
                  name="sku_code"
                  rules={[{ required: true, message: "请输入 SKU 编码" }]}
                >
                  <Input placeholder={`SKU-${Date.now()}`} />
                </Form.Item>
                <Form.Item
                  label="类目"
                  name="category"
                  rules={[{ required: true, message: "请选择类目" }]}
                  initialValue="连衣裙"
                >
                  <Select options={CATEGORY_OPTIONS_SELECT} />
                </Form.Item>
                <Form.Item
                  label="价格区间"
                  style={{ marginBottom: 0 }}
                >
                  <div className="flex items-center gap-2">
                    <Form.Item
                      name="price_min"
                      noStyle
                      dependencies={["price_max"]}
                      rules={[
                        { required: true, message: "请输入最低价" },
                        { type: "number", min: 0, message: "最低价不能小于0" },
                        ({ getFieldValue }) => ({
                          validator(_, value) {
                            const max = getFieldValue("price_max");
                            if (max != null && value != null && value > max) {
                              return Promise.reject(new Error("最低价不能超过最高价"));
                            }
                            return Promise.resolve();
                          },
                        }),
                      ]}
                      initialValue={15}
                    >
                      <InputNumber
                        id="price_min"
                        min={0}
                        precision={0}
                        prefix="$"
                        placeholder="最低价"
                        style={{ width: 100 }}
                      />
                    </Form.Item>
                    <span className="text-gray-400">—</span>
                    <Form.Item
                      name="price_max"
                      noStyle
                      dependencies={["price_min"]}
                      rules={[
                        { required: true, message: "请输入最高价" },
                        { type: "number", min: 0, message: "最高价不能小于0" },
                        ({ getFieldValue }) => ({
                          validator(_, value) {
                            const min = getFieldValue("price_min");
                            if (min != null && value != null && value < min) {
                              return Promise.reject(new Error("最高价不能低于最低价"));
                            }
                            return Promise.resolve();
                          },
                        }),
                      ]}
                      initialValue={25}
                    >
                      <InputNumber
                        id="price_max"
                        min={0}
                        precision={0}
                        prefix="$"
                        placeholder="最高价"
                        style={{ width: 100 }}
                      />
                    </Form.Item>
                  </div>
                </Form.Item>
                <Form.Item
                  label="主推市场"
                  name="target_market"
                  rules={[{ required: true, message: "请选择主推市场" }]}
                  initialValue="us"
                  help="用于三维度融合推荐的市场本地化维度"
                >
                  <Select options={MARKET_OPTIONS_SELECT} />
                </Form.Item>
              </div>
              <Form.Item
                label="商品图片 URL"
                name="image_url"
                rules={[{ required: true, message: "请输入商品平铺图 URL" }]}
                help="输入 MinIO 或 CDN 上的商品平铺图地址"
              >
                <Input placeholder="https://cdn.example.com/product/flatlay.jpg" />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                loading={createProduct.isPending}
                icon={<InboxOutlined />}
              >
                创建商品并推荐方案
              </Button>
            </Form>
          </Card>
          </>
        )}

        {/* Step 1: 选择推荐方案 */}
        {step === 1 && (
          <div className="space-y-4">
            <Card>
              <p className="text-sm text-gray-500">
                商品已创建：
                <Tag color="green" className="ml-2">ID: {productId}</Tag>
                <Tag color="cyan" className="ml-2">品类: {productCategory}</Tag>
                <Tag color="orange" className="ml-2">主推市场: {targetMarket.toUpperCase()}</Tag>
                {productImageUrl && (
                  <Tag color="blue" className="ml-2">图片已关联</Tag>
                )}
              </p>
            </Card>

            {/* 三维度融合推荐（战略层：风格建议 + 可解释理由） */}
            {recommendFusion.isPending ? (
              <Card>
                <div className="flex items-center gap-2 mb-2">
                  <BulbOutlined className="text-purple-500" />
                  <span className="font-semibold">三维度融合推荐分析中...</span>
                </div>
                <p className="text-sm text-gray-400">
                  正在融合同品类历史 CTR + 跨品类迁移趋势 + 市场本地化偏好...
                </p>
              </Card>
            ) : recommendFusion.data && recommendFusion.data.recommendations.length > 0 ? (
              <Card
                className="border-purple-100"
                title={
                  <div className="flex items-center gap-2">
                    <BulbOutlined className="text-purple-500" />
                    <span className="font-semibold">三维度融合推荐</span>
                    <Tag color="purple" className="ml-1">战略层建议</Tag>
                  </div>
                }
              >
                {/* 三维度权重展示 */}
                <div className="grid grid-cols-3 gap-3 mb-4 p-3 bg-purple-50 rounded">
                  {(["same_category", "cross_category", "market"] as FusionDimension[]).map((dim) => (
                    <div key={dim} className="text-center">
                      <div className="text-xs text-gray-500 mb-1">{FUSION_DIM_LABELS[dim]}</div>
                      <Progress
                        percent={Math.round((recommendFusion.data!.weights[dim] ?? 0) * 100)}
                        size="small"
                        strokeColor={dim === "same_category" ? "#2563EB" : dim === "cross_category" ? "#722ed1" : "#fa8c16"}
                        format={(p) => `${p}%`}
                      />
                    </div>
                  ))}
                </div>

                {/* 推荐风格卡片网格 */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {recommendFusion.data.recommendations.map((rec, idx) => (
                    <Card
                      key={`${rec.scheme_name}-${idx}`}
                      size="small"
                      className="border-purple-100"
                      title={
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-sm">{rec.scheme_name}</span>
                          <Tag color="purple">
                            融合分 {(rec.recommendation_score * 100).toFixed(1)}
                          </Tag>
                        </div>
                      }
                    >
                      {/* 维度来源标签 */}
                      <div className="flex flex-wrap gap-1 mb-2">
                        {rec.dimensions.map((dim) => (
                          <Tag key={dim} color={FUSION_DIM_COLORS[dim]} className="text-xs">
                            {FUSION_DIM_LABELS[dim]}
                          </Tag>
                        ))}
                      </div>

                      {/* 可解释理由 */}
                      <p className="text-xs text-gray-600 leading-relaxed mb-2">
                        {rec.reason}
                      </p>

                      {/* 量化指标 */}
                      <div className="flex flex-wrap gap-2 text-xs text-gray-400 pt-2 border-t border-gray-50">
                        {rec.metrics.avg_ctr != null && (
                          <Tooltip title="历史平均 CTR">
                            <span>CTR: {(rec.metrics.avg_ctr * 100).toFixed(2)}%</span>
                          </Tooltip>
                        )}
                        {rec.metrics.total_impressions != null && (
                          <Tooltip title="历史曝光总量">
                            <span>曝光: {rec.metrics.total_impressions}</span>
                          </Tooltip>
                        )}
                        {rec.metrics.category_count != null && (
                          <Tooltip title="覆盖品类数">
                            <span>覆盖品类: {rec.metrics.category_count}</span>
                          </Tooltip>
                        )}
                        {rec.metrics.avg_return_rate != null && (
                          <Tooltip title="平均退货率">
                            <span>退货率: {(rec.metrics.avg_return_rate * 100).toFixed(1)}%</span>
                          </Tooltip>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>

                <p className="text-xs text-gray-400 mt-3">
                  以上为风格层面的战略建议（无具体方案 ID），请结合下方 CLIP 检索的具体方案选择生成
                </p>
              </Card>
            ) : null}

            {/* CLIP 相似度检索（战术层：可选具体方案） */}
            {recommendSchemes.isPending ? (
              <Card className="text-center py-12">
                <p className="text-gray-400">正在通过 CLIP 检索最适配的具体方案...</p>
              </Card>
            ) : schemes.length > 0 ? (
              <>
                <div className="flex items-center gap-2 px-1">
                  <span className="font-semibold">具体方案选择</span>
                  <Tag color="blue">CLIP 检索</Tag>
                  <span className="text-xs text-gray-400">— 战术层，可选择用于生成</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {schemes.map((s) => (
                    <SchemeCard
                      key={s.id}
                      scheme={s}
                      selected={selectedSchemes.some((sel) => sel.id === s.id)}
                      onSelect={handleToggleScheme}
                    />
                  ))}
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-400">
                    已选择 {selectedSchemes.length} 套方案（最多 3 套）
                  </span>
                  <Button
                    type="primary"
                    size="large"
                    disabled={selectedSchemes.length === 0}
                    onClick={handleStartGen}
                    loading={startGeneration.isPending}
                  >
                    开始 AI 生成
                  </Button>
                </div>
              </>
            ) : (
              <Card className="text-center py-8">
                <p className="text-gray-400">暂无可推荐方案</p>
                <Button
                  type="primary"
                  className="mt-4"
                  onClick={() => {
                    recommendSchemes.mutate({ imageUrl: productImageUrl, topK: 5 });
                    if (productCategory) {
                      recommendFusion.mutate({ category: productCategory, market: targetMarket, top_k: 5 });
                    }
                  }}
                  loading={recommendSchemes.isPending || recommendFusion.isPending}
                >
                  重新分析
                </Button>
              </Card>
            )}
          </div>
        )}

        {/* Step 2: 生成进度 */}
        {step === 2 && (
          <div className="space-y-4">
            {taskImageIds.map((imageId) => (
              <TaskGenerateProgress key={imageId} imageId={imageId} />
            ))}
            <div className="flex justify-end gap-3">
              <Button onClick={() => setStep(3)}>查看结果</Button>
            </div>
          </div>
        )}

        {/* Step 3: 质检对比 */}
        {step === 3 && (
          <div className="space-y-8">
            {taskImageIds.map((imageId) => (
              <TaskResultView
                key={imageId}
                imageId={imageId}
                productId={productId}
                publishing={publishing}
                setPublishing={setPublishing}
                onBack={() => setStep(1)}
              />
            ))}
            <div className="flex justify-end gap-3">
              <Button onClick={() => setStep(1)}>返回修改方案</Button>
            </div>
          </div>
        )}
      </div>
  );
}

// 单任务生成进度

function TaskGenerateProgress({ imageId }: { imageId: number }) {
  const { data: genStatus } = useGenerationStatus(imageId, 3000);

  return (
    <GenerateProgress
      total={1}
      completed={genStatus?.status === "completed" ? 1 : 0}
      images={
        genStatus?.image_url
          ? [
              {
                id: genStatus.image_id,
                imageUrl: genStatus.image_url,
                score: genStatus.overall_score,
                status:
                  genStatus.status === "completed" ? "approved" : "pending",
              },
            ]
          : []
      }
    />
  );
}

// 单任务质检结果

function TaskResultView({
  imageId,
  productId,
  publishing,
  setPublishing,
  onBack,
}: {
  imageId: number;
  productId: number | null;
  publishing: boolean;
  setPublishing: (v: boolean) => void;
  onBack: () => void;
}) {
  const { data: genStatus } = useGenerationStatus(imageId, 3000);
  const { message } = App.useApp();

  if (!genStatus?.image_url) return null;

  return (
    <div className="space-y-4">
      {/* 质检结论提示 */}
      {genStatus.review_status === "auto_approved" ? (
        <Alert
          type="success"
          showIcon
          title={`图片 #${imageId} 质检通过`}
          description={`综合评分 ${genStatus.overall_score?.toFixed(1) ?? "—"} 分，已自动通过质检，可发布上线`}
        />
      ) : genStatus.review_status === "manual_pending" ? (
        <Alert
          type="warning"
          showIcon
          title={`图片 #${imageId} 待人工审核`}
          description={`综合评分 ${genStatus.overall_score?.toFixed(1) ?? "—"} 分，处于人工复审区间（60-75 分），请审核后决定`}
        />
      ) : (
        <Alert
          type="error"
          showIcon
          title={`图片 #${imageId} 质检未通过`}
          description={`综合评分 ${genStatus.overall_score?.toFixed(1) ?? "—"} 分，低于 60 分阈值，建议重新生成`}
        />
      )}

      {/* 图片对比 */}
      <ComparisonViewer
        images={[
          {
            id: genStatus.image_id,
            imageUrl: genStatus.image_url,
            score: genStatus.overall_score,
            label: "US 市场",
            market: "us",
            status: genStatus.review_status,
          },
        ]}
        onApproveAll={() => message.success("已全部采纳")}
      />

      {/* 质检详情：L2 雷达 + L1 合规 + L3 审美 */}
      {genStatus.quality_scores && (
        <div className="grid grid-cols-2 gap-4">
          <QualityRadar
            overallScore={genStatus.overall_score}
            reviewStatus={genStatus.review_status || "manual_pending"}
            dimensions={genStatus.quality_scores.l2?.dimensions}
            failedDimensions={
              genStatus.quality_scores.l2?.verdict === "fail"
                ? Object.keys(genStatus.quality_scores.l2.dimensions)
                : []
            }
          />

          <div className="space-y-3">
            {/* L1 合规 */}
            {genStatus.quality_scores.l1 && (
              <Card size="small">
                <div className="flex items-center gap-2 mb-2">
                  <SafetyCertificateOutlined />
                  <span className="font-semibold text-sm">L1 合规层</span>
                  <Tag color={genStatus.quality_scores.l1.passed ? "green" : "red"}>
                    {genStatus.quality_scores.l1.passed ? "通过" : "未通过"}
                  </Tag>
                </div>
                <div className="text-xs text-gray-500 space-y-1">
                  {genStatus.quality_scores.l1.checks.map((c, idx) => (
                    <div key={idx} className="flex items-center gap-1">
                      {c.passed ? (
                        <CheckCircleOutlined className="text-green-400" />
                      ) : (
                        <CloseCircleOutlined className="text-red-400" />
                      )}
                      <span>
                        {L1_DIM_LABELS[c.dimension] || c.dimension}：{c.actual}
                        {c.passed ? "" : `（要求：${c.requirement}）`}
                      </span>
                    </div>
                  ))}
                  {genStatus.c2pa_manifest && (
                    <div className="flex items-center gap-1">
                      <CheckCircleOutlined className="text-green-400" />
                      <span>C2PA 内容溯源已附加</span>
                    </div>
                  )}
                </div>
              </Card>
            )}

            {/* L3 审美 */}
            {genStatus.quality_scores.l3 && (
              <Card size="small">
                <div className="font-semibold text-sm mb-2">L3 审美层</div>
                <div className="space-y-1">
                  {Object.entries(genStatus.quality_scores.l3).map(([key, val]) => (
                    <div key={key} className="flex items-center justify-between text-xs">
                      <span className="text-gray-500">{L3_LABELS[key] || key}</span>
                      <span className={`font-semibold ${
                        val >= 75 ? "text-green-500" : val >= 60 ? "text-yellow-500" : "text-red-500"
                      }`}>
                        {val.toFixed(1)}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* 生成参数 */}
      {genStatus.generation_params && (
        <>
          <Divider className="my-2" />
          <Descriptions title="生成参数" size="small" column={2} bordered>
            {Boolean(genStatus.generation_params.model) && (
              <Descriptions.Item label="模型">
                {String(genStatus.generation_params.model)}
              </Descriptions.Item>
            )}
            {Boolean(genStatus.generation_params.prompt) && (
              <Descriptions.Item label="Prompt" span={2}>
                <span className="text-xs text-gray-600">
                  {String(genStatus.generation_params.prompt)}
                </span>
              </Descriptions.Item>
            )}
            {Boolean(genStatus.generation_params.steps) && (
              <Descriptions.Item label="步数">
                {String(genStatus.generation_params.steps)}
              </Descriptions.Item>
            )}
            {Boolean(genStatus.generation_params.guidance_scale) && (
              <Descriptions.Item label="引导系数">
                {String(genStatus.generation_params.guidance_scale)}
              </Descriptions.Item>
            )}
          </Descriptions>
        </>
      )}

      {/* 操作按钮 */}
      <div className="flex justify-end gap-3">
        <Button onClick={onBack}>重新选择方案</Button>
        {genStatus.review_status === "rejected" ? (
          <Button type="primary" size="large" onClick={onBack}>
            重新生成
          </Button>
        ) : (
          <Button
            type="primary"
            size="large"
            loading={publishing}
            onClick={async () => {
              if (!productId) return;
              setPublishing(true);
              try {
                message.loading({ content: "正在发布...", key: "publish" });
                await api.publishProduct(productId);
                message.success({ content: "已发布上线", key: "publish" });
              } catch {
                message.error({ content: "发布失败，请重试", key: "publish" });
              } finally {
                setPublishing(false);
              }
            }}
          >
            发布上线
          </Button>
        )}
      </div>
    </div>
  );
}
