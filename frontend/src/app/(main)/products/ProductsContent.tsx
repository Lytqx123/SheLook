"use client";

import { useState } from "react";
import {
  Card, Table, Button, Modal, Form, Input, Select, Tag, Space,
  App, Popconfirm, Typography,
} from "antd";
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ShopOutlined, CloudUploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import PageHeader from "@/components/PageHeader";
import {
  useProducts, useCreateProduct, useUpdateProduct, useDeleteProduct, usePublishProduct,
} from "@/hooks";
import { CATEGORY_OPTIONS_SELECT, MARKET_OPTIONS_SELECT } from "@/constants";
import type { Product, ProductCreate } from "@/types";

const { Text } = Typography;

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: "default", label: "草稿" },
  published: { color: "green", label: "已发布" },
  archived: { color: "red", label: "已归档" },
};

export default function ProductsContent() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const { data, isPending } = useProducts(page, pageSize);

  const createMutation = useCreateProduct();
  const updateMutation = useUpdateProduct();
  const deleteMutation = useDeleteProduct();
  const publishMutation = usePublishProduct();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [form] = Form.useForm<ProductCreate>();
  const { message } = App.useApp();

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Product) => {
    setEditing(record);
    form.setFieldsValue({
      sku_code: record.sku_code,
      title: record.title,
      category: record.category,
      price_range: record.price_range,
      target_markets: record.target_markets,
      supplier_id: record.supplier_id,
      image_raw_url: record.image_raw_url,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editing) {
        await updateMutation.mutateAsync({ id: editing.id, body: values });
        message.success("商品已更新");
      } else {
        await createMutation.mutateAsync(values);
        message.success("商品已创建");
      }
      setModalOpen(false);
    } catch (e: unknown) {
      if (e instanceof Error) message.error(e.message);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMutation.mutateAsync(id);
      message.success("商品已删除");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handlePublish = async (id: number) => {
    try {
      await publishMutation.mutateAsync(id);
      message.success("商品已发布");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "发布失败");
    }
  };

  const columns: ColumnsType<Product> = [
    { title: "ID", dataIndex: "id", key: "id", width: 70 },
    { title: "SKU", dataIndex: "sku_code", key: "sku", width: 140 },
    { title: "标题", dataIndex: "title", key: "title", ellipsis: true },
    { title: "品类", dataIndex: "category", key: "category", width: 100 },
    {
      title: "目标市场",
      dataIndex: "target_markets",
      key: "markets",
      width: 160,
      render: (markets?: string[]) =>
        markets?.length ? (
          <Space size={4} wrap>
            {markets.map((m) => <Tag key={m} color="blue">{m}</Tag>)}
          </Space>
        ) : <Text type="secondary">—</Text>,
    },
    {
      title: "方案数",
      key: "schemes",
      width: 80,
      render: (_, r) => <Tag>{r.schemes?.length ?? 0}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => {
        const m = STATUS_MAP[status] ?? { color: "default", label: status };
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 120,
      render: (v?: string) => (v ? new Date(v).toLocaleDateString("zh-CN") : "—"),
    },
    {
      title: "操作",
      key: "action",
      width: 200,
      fixed: "right",
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          {record.status === "draft" && (
            <Popconfirm
              title="确认发布该商品？"
              description="发布后将在各目标市场上线"
              onConfirm={() => handlePublish(record.id)}
              okText="发布"
              cancelText="取消"
            >
              <Button type="link" size="small" icon={<CloudUploadOutlined />}>
                发布
              </Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确认删除该商品？"
            description="删除后将归档，不可恢复"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="商品管理"
        subtitle="管理所有商品 SKU、品类、目标市场与关联视觉方案"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} size="large">
            新建商品
          </Button>
        }
      />

      <Card>
        <Table
          columns={columns}
          dataSource={data?.items ?? []}
          rowKey="id"
          loading={isPending}
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
        />
      </Card>

      <Modal
        title={editing ? `编辑商品 #${editing.id}` : "新建商品"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText={editing ? "保存" : "创建"}
        cancelText="取消"
        width={560}
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="sku_code" label="SKU 编码" rules={[{ required: true, message: "请输入 SKU" }]}>
            <Input placeholder="如 DRESS-001" />
          </Form.Item>
          <Form.Item name="title" label="商品标题" rules={[{ required: true, message: "请输入标题" }]}>
            <Input placeholder="商品名称" />
          </Form.Item>
          <Form.Item name="category" label="品类" rules={[{ required: true, message: "请选择品类" }]}>
            <Select options={CATEGORY_OPTIONS_SELECT} placeholder="选择品类" />
          </Form.Item>
          <Form.Item name="target_markets" label="目标市场">
            <Select mode="multiple" options={MARKET_OPTIONS_SELECT} placeholder="选择目标市场" />
          </Form.Item>
          <Form.Item name="price_range" label="价格区间">
            <Input placeholder="如 $10-$30" />
          </Form.Item>
          <Form.Item name="supplier_id" label="供应商 ID">
            <Input placeholder="供应商标识" />
          </Form.Item>
          <Form.Item name="image_raw_url" label="原图 URL">
            <Input placeholder="商品原图地址" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
