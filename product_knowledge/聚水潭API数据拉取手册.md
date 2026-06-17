# 聚水潭 OpenAPI 数据拉取手册

> 签名算法: `MD5(app_secret + sorted(key+value, 无分隔符))`
> 请求格式: POST form-data
> 基础URL: `https://openapi.jushuitan.com/open`
> 所有接口通用参数: `app_key`, `access_token`, `timestamp`, `charset=utf-8`, `version=2`, `sign`, `biz`(JSON字符串)

---

## 通用调用代码

```python
import hashlib, json, time, requests

# ⚠️ 凭证从环境变量读取，不要硬编码！
# 设置: JUSHUITAN_APP_KEY, JUSHUITAN_APP_SECRET, JUSHUITAN_ACCESS_TOKEN
import os
APP_KEY = os.environ.get("JUSHUITAN_APP_KEY", "")
APP_SECRET = os.environ.get("JUSHUITAN_APP_SECRET", "")
ACCESS_TOKEN = os.environ.get("JUSHUITAN_ACCESS_TOKEN", "")
BASE_URL = os.environ.get("JUSHUITAN_BASE_URL", "https://openapi.jushuitan.com/open")

def generate_sign(app_secret, params):
    sorted_params = sorted(params.items())
    sign_str = app_secret + ''.join(f"{k}{v}" for k, v in sorted_params)
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest()

def call_api(endpoint, biz_params=None):
    ts = str(int(time.time()))
    biz_str = json.dumps(biz_params or {}, separators=(',', ':'), ensure_ascii=False)
    params = {
        'access_token': ACCESS_TOKEN,
        'app_key': APP_KEY,
        'biz': biz_str,
        'charset': 'utf-8',
        'timestamp': ts,
        'version': '2',
    }
    params['sign'] = generate_sign(APP_SECRET, params)
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.post(url, data=params, timeout=15)
    return resp.json()
```

---

## 一、商品API

### 1.1 SKU查询

- **端点**: `/open/sku/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天) 或 `sku_ids`(SKU编码列表)
- **可选参数**: `page_index`(默认1), `page_size`(默认10)
- **调用示例**:
```python
call_api("sku/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **返回字段**: `sku_id`(SKU编码), `i_id`(款号), `name`, `pic`(图片), `brand`(品牌), `weight`, `item_type`(商品类型), `modified`, `created`, `labels` 等
- **分页**: `data.total`为总数, `data.datas`为列表

### 1.2 店铺商品资料查询

- **端点**: `/open/skumap/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天) 或 `sku_ids`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("skumap/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **说明**: 查询SKU与店铺商品的映射关系

### 1.3 组合装商品查询

- **端点**: `/open/combine/sku/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天) 或 `sku_ids`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("combine/sku/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 1.4 普通商品查询（按款查询）

- **端点**: `/open/mall/item/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天) 或 `i_ids`(款号列表)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("mall/item/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **说明**: 按款号查询商品，一个款号下可包含多个SKU

### 1.5 商品BOM信息查询

- **端点**: `/open/webapi/itemapi/bom/getskubompagelist`
- **类型**: 查询
- **必填参数**: `sku_ids`(SKU编码列表) + `modified_begin` + `modified_end`(必须同时传)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("webapi/itemapi/bom/getskubompagelist", {
    "page_index": 1,
    "page_size": 100,
    "sku_ids": ["YH45K01B01S26", "YH45K01B02S12"],
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **说明**: 查询组合装的BOM(物料清单)信息

### 1.6 商品类目查询

- **端点**: `/open/category/query`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("category/query", {
    "page_index": 1,
    "page_size": 100
})
```
- **说明**: 查询商品分类树，返回类目ID和名称

### 1.7 商品恢复数据查询

- **端点**: `/open/webapi/itemapi/itemsku/queryitemskuopshistory`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("webapi/itemapi/itemsku/queryitemskuopshistory", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59"
})
```
- **说明**: 查询商品的操作历史记录（删除/修改等）

### 1.8 商品多供应商查询

- **端点**: `/open/webapi/itemapi/suppliersku/getsupplierskulist`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("webapi/itemapi/suppliersku/getsupplierskulist", {
    "page_index": 1,
    "page_size": 100
})
```
- **说明**: 查询商品关联的多个供应商信息

### 1.9 商品历史成本价查询V2

- **端点**: `/open/webapi/itemapi/itemsku/gethistorycostpricev2`
- **类型**: 查询
- **必填参数**: `sku_ids`(SKU编码列表)
- **调用示例**:
```python
call_api("webapi/itemapi/itemsku/gethistorycostpricev2", {
    "sku_ids": ["YH45K01B01S26", "YH45K01B02S12"]
})
```
- **返回字段**: `cost_price`(成本价), `begin_date`(生效日期), `end_date`(失效日期), `company_name`(仓储方) 等
- **说明**: 根据SKU编码批量获取历史成本价

---

## 二、库存API

### 2.1 库存查询

- **端点**: `/open/inventory/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`, `sku_ids`(按SKU过滤), `wms_co_id`(按仓库过滤)
- **调用示例**:
```python
call_api("inventory/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **返回字段**: `sku_id`, `name`, `qty`(库存数量), `wms_co_id`, `properties_value`(规格) 等

### 2.2 库存盘点查询

- **端点**: `/open/inventory/count/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("inventory/count/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 2.3 箱及仓位库存查询

- **端点**: `/open/webapi/wmsapi/pack/pagequerypackanditems`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("webapi/wmsapi/pack/pagequerypackanditems", {
    "page_index": 1,
    "page_size": 100
})
```
- **说明**: 查询仓库中箱和仓位的库存明细

---

## 三、订单API

### 3.1 订单查询

- **端点**: `/open/orders/single/query`
- **类型**: 查询 (该接口同时支持修改操作，见下方警告)
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`, `shop_id`(按店铺过滤), `status`(订单状态)
- **调用示例**:
```python
call_api("orders/single/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```
- **返回字段**: `o_id`(订单号), `shop_id`, `status`, `receiver_name`, `receiver_address`, `items`(商品明细), `created`, `modified` 等
- **分页**: `data.total`为总数, `data.orders`为列表

> **WARNING: 严禁修改**
> 该API所属的"订单API"模块同时包含修改类接口（如批量修改、拆分、合并、审核等）。本手册仅允许使用**查询**功能，严禁调用任何修改操作的端点。

---

## 四、物流API

### 4.1 发货信息查询

- **端点**: `/open/logistic/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天) 或 `order_ids`(订单号列表)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("logistic/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 4.2 快递登记查询

- **端点**: `/open/webapi/aftersaleapi/getasexpress`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`(只能为100, 200或500)
- **调用示例**:
```python
call_api("webapi/aftersaleapi/getasexpress", {
    "page_index": 1,
    "page_size": 100
})
```
- **注意**: `page_size` 只能传 100、200 或 500

> **WARNING: 严禁修改**
> 物流API模块同时包含"称重并发货"、"批量快递登记"、"出库发货"等修改类接口。本手册仅允许使用**查询**功能。

---

## 五、采购API

### 5.1 采购单查询

- **端点**: `/open/purchase/query`
- **类型**: 查询 (该接口同时支持修改操作，见下方警告)
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("purchase/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 5.2 预约入库查询列表

- **端点**: `/open/jushuitan/purchasebooking/query`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("jushuitan/purchasebooking/query", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59"
})
```

### 5.3 加工单查询

- **端点**: `/open/jushuitan/manufacture/query`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("jushuitan/manufacture/query", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59"
})
```

### 5.4 供应商查询

- **端点**: `/open/supplier/query`
- **类型**: 查询 (该接口同时支持修改操作，见下方警告)
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("supplier/query", {
    "page_index": 1,
    "page_size": 100
})
```

> **WARNING: 严禁修改**
> 采购API模块同时包含"采购单上传"、"采购单状态变更"、"采购单作废"、"修改采购单"、"供应商上传"、"加工单上传"、"预约入库上传"等修改类接口。本手册仅允许使用**查询**功能。

---

## 六、入库API

### 6.1 采购入库查询

- **端点**: `/open/webapi/wmsapi/purchasein/purchaseinquery`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("webapi/wmsapi/purchasein/purchaseinquery", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

> **WARNING: 严禁修改**
> 入库API模块同时包含"生成采购入库单"、"采购入库取消"、"入库单确认"、"批量录入唯一码"、"批量录入箱唯一码"、"生产批次管理创建"等修改类接口。本手册仅允许使用**查询**功能。

---

## 七、出库API

### 7.1 采购退货查询

- **端点**: `/open/purchaseout/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("purchaseout/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 7.2 销售出库查询

- **端点**: `/open/orders/out/simple/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("orders/out/simple/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

> **WARNING: 严禁修改**
> 出库API模块同时包含"生成采购退货单"、"出库发货"、"采购退货取消"等修改类接口。本手册仅允许使用**查询**功能。

---

## 八、售后API

### 8.1 退货退款查询

- **端点**: `/open/refund/single/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("refund/single/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

### 8.2 实际收货查询

- **端点**: `/open/aftersale/received/query`
- **类型**: 查询
- **必填参数**: `modified_begin` + `modified_end`(时间范围<=7天)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("aftersale/received/query", {
    "page_index": 1,
    "page_size": 100,
    "modified_begin": "2026-05-17 00:00:00",
    "modified_end": "2026-05-22 23:59:59"
})
```

> **WARNING: 严禁修改**
> 售后API模块同时包含"售后上传"、"售后确认收货"、"售后单确认"、"售后单作废"、"售后单反确认"、"设置售后标签"、"唯一码批量确认收货"、"售后上传(无信息件)"等修改类接口。本手册仅允许使用**查询**功能。

---

## 九、财务API

### 9.1 费用项目查询

- **端点**: `/open/api/fmsopen/queryfinanceproject`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("api/fmsopen/queryfinanceproject", {
    "page_index": 1,
    "page_size": 100
})
```

### 9.2 业务费用列表查询

- **端点**: `/open/api/fmsopen/queryoperatingfee`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("api/fmsopen/queryoperatingfee", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59"
})
```

### 9.3 应付单列表查询

- **端点**: `/open/api/fmsopen/querypayable`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time` + `type`(1或2)
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("api/fmsopen/querypayable", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59",
    "type": 1
})
```
- **注意**: `type` 为必填项，可选值为 `1` 或 `2`

### 9.4 付款单列表查询

- **端点**: `/open/api/fmsopen/querypayment`
- **类型**: 查询
- **必填参数**: `start_time` + `end_time`
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("api/fmsopen/querypayment", {
    "page_index": 1,
    "page_size": 100,
    "start_time": "2026-05-17 00:00:00",
    "end_time": "2026-05-22 23:59:59"
})
```

---

## 十、基础数据API

### 10.1 店铺查询

- **端点**: `/open/shops/query`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("shops/query", {
    "page_index": 1,
    "page_size": 100
})
```
- **返回字段**: `shop_id`(店铺ID), `shop_name`(店铺名称), `shop_site`(平台类型) 等
- **实测数据**: 共61个店铺

### 10.2 物流公司查询

- **端点**: `/open/logisticscompany/query`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("logisticscompany/query", {
    "page_index": 1,
    "page_size": 500
})
```
- **返回字段**: `lc_id`(物流公司编码), `lc_name`(物流公司名称) 等

### 10.3 仓库查询

- **端点**: `/open/wms/partner/query`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_index`, `page_size`
- **调用示例**:
```python
call_api("wms/partner/query", {
    "page_index": 1,
    "page_size": 50
})
```
- **返回字段**: `wms_co_id`(仓库ID), `name`(仓库名称), `is_main`(是否主仓) 等
- **实测数据**: 主仓 `wms_co_id=12124122`

### 10.4 商家用户信息

- **端点**: `/open/webapi/userapi/company/getcompanyusers`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `current_page`, `page_size`, `page_action`
- **调用示例**:
```python
call_api("webapi/userapi/company/getcompanyusers", {
    "current_page": 1,
    "page_size": 100,
    "page_action": 0
})
```
- **返回字段**: `u_id`(用户ID), `name`(用户名), `enabled`(是否启用) 等
- **实测数据**: 共73个用户

### 10.5 供应商列表（分销）

- **端点**: `/open/api/drp/inneropen/partner/channel/querymysupplier`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_num`, `page_size`
- **调用示例**:
```python
call_api("api/drp/inneropen/partner/channel/querymysupplier", {
    "page_num": 1,
    "page_size": 100
})
```
- **返回字段**: `supplier_co_id`(供应商公司ID), `co_name`(公司名称), `status`(状态) 等
- **实测数据**: 共3个供应商

### 10.6 分销商查询

- **端点**: `/open/api/drp/inneropen/partner/supplier/querymychannel`
- **类型**: 查询
- **必填参数**: 无
- **可选参数**: `page_num`, `page_size`
- **调用示例**:
```python
call_api("api/drp/inneropen/partner/supplier/querymychannel", {
    "page_num": 1,
    "page_size": 100
})
```
- **返回字段**: `channel_co_id`(分销商公司ID), `co_name`(公司名称), `status`(状态) 等
- **实测数据**: 共60个分销商

---

## 附录

### A. 常见错误码

| 错误码 | 含义 | 解决方法 |
|--------|------|----------|
| 0 | 成功 | - |
| 10 | 无效签名 | 检查签名算法，确保参数排序正确 |
| 100 | 无效/过期token | 检查access_token是否正确，是否过期 |
| 130 | 缺少必填参数 | 检查biz中的必填字段 |
| 140 | 数据格式错误 | 检查请求格式是否为form-data |
| 170 | 验证失败 | 检查参数值是否符合要求 |
| 190 | 无API权限 | 在开放平台后台申请权限 |
| 10015 | 参数缺失 | 检查必填参数是否传全 |
| -4 | 参数值错误 | 检查参数可选值范围 |

### B. 重要注意事项

1. **时间范围限制**: 大部分查询接口的时间范围不能超过7天，建议分批查询
2. **分页**: 默认每页10条，建议设置为100以减少请求次数
3. **频率限制**: 大部分接口5次/秒、100次/分钟，请做好限流
4. **严禁修改**: 标注了"严禁修改"的模块，只允许调用查询接口，绝不调用上传/修改/删除/确认/作废等操作
5. **access_token有效期**: 180天（15552000秒），过期需刷新

### C. 已授权但本手册不记录的修改类接口

以下接口已授权但属于修改类操作，**严禁调用**：

- 商品: 批量上传商品、组合装上传、普通商品上传、店铺商品上传、商品款式更新、商品历史成本价上传、BOM保存、分类新增/修改、绑定/解绑商品关系、更新供应商商品、更新库容信息
- 库存: 新建盘点单、更新虚拟库存
- 物流: 称重并发货、批量快递登记、出库发货
- 采购: 采购单上传、采购单状态变更、采购单作废、修改采购单、供应商上传、加工单上传、预约入库上传、采购单标签
- 入库: 生成采购入库单、采购入库取消、入库单确认、批量录入唯一码、批量录入箱唯一码、生产批次管理创建
- 出库: 生成采购退货单、采购退货取消
- 售后: 售后上传、售后确认收货、售后单确认、售后单作废、售后单反确认、设置售后标签、唯一码批量确认收货、售后上传(无信息件)
