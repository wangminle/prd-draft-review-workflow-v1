# Category Configuration Examples

Domain-specific category configurations for common use cases. Copy the one that fits your project, save as a JSON file, and pass with `--categories`.

## Smart Home (智能家居)

```json
{
  "categories": [
    {
      "name": "核心策略",
      "keywords": ["云端", "判定", "算法", "策略", "下发", "参数"],
      "description": "涉及智能判定逻辑、算法策略、参数配置"
    },
    {
      "name": "交互体验",
      "keywords": ["体验", "UI", "动效", "灯效", "应答", "播报", "回复", "交互"],
      "description": "涉及用户交互体验、UI动效、语音应答"
    },
    {
      "name": "效果评估",
      "keywords": ["评估", "数据追踪", "查询", "Portal", "详情页"],
      "description": "涉及效果评估方案、数据追踪、数据查询系统"
    },
    {
      "name": "App交互",
      "keywords": ["App", "页面", "交互", "开关", "音箱端"],
      "description": "涉及App端交互设计、页面展示、设置项"
    },
    {
      "name": "调研竞品",
      "keywords": ["调研", "竞品", "用户意愿", "洞察"],
      "description": "涉及用户调研、竞品分析、体验洞察"
    },
    {
      "name": "功能预约",
      "keywords": ["预约", "功能", "定时", "家电", "空调", "厨电", "采暖", "洗衣"],
      "description": "涉及功能预约、定时任务、品类扩展"
    }
  ],
  "version_pattern": "V\\d+\\.\\d+[\\.\\d]*",
  "subcategory_pattern": "【(.+?)v(\\d+)】"
}
```

## SaaS Platform

```json
{
  "categories": [
    {
      "name": "用户体系",
      "keywords": ["用户", "注册", "登录", "权限", "角色"],
      "description": "涉及用户注册、认证、权限管理"
    },
    {
      "name": "计费支付",
      "keywords": ["计费", "支付", "订单", "账单", "订阅"],
      "description": "涉及计费逻辑、支付流程、订单管理"
    },
    {
      "name": "数据平台",
      "keywords": ["数据", "报表", "分析", "仪表盘", "导出"],
      "description": "涉及数据分析、报表、可视化"
    },
    {
      "name": "集成开放",
      "keywords": ["API", "SDK", "Webhook", "集成", "开放平台"],
      "description": "涉及对外API、SDK、第三方集成"
    },
    {
      "name": "运维安全",
      "keywords": ["监控", "告警", "日志", "安全", "审计"],
      "description": "涉及运维监控、安全审计、日志"
    }
  ],
  "version_pattern": "v\\d+\\.\\d+\\.\\d+",
  "subcategory_pattern": "\\[(.+?)#(\\d+)\\]"
}
```

## E-commerce

```json
{
  "categories": [
    {
      "name": "商品管理",
      "keywords": ["商品", "SKU", "SPU", "类目", "属性"],
      "description": "涉及商品创建、编辑、类目管理"
    },
    {
      "name": "交易履约",
      "keywords": ["订单", "支付", "退款", "发货", "物流"],
      "description": "涉及订单流转、支付、物流履约"
    },
    {
      "name": "营销促销",
      "keywords": ["优惠券", "活动", "拼团", "秒杀", "满减"],
      "description": "涉及营销工具、促销活动"
    },
    {
      "name": "搜索推荐",
      "keywords": ["搜索", "推荐", "排序", "索引", "召回"],
      "description": "涉及搜索引擎、推荐算法"
    }
  ],
  "version_pattern": "V\\d+\\.\\d+",
  "subcategory_pattern": "【(.+?)v(\\d+)】"
}
```
