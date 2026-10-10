# HTTP Server 与后端通信

## 方案一：用 fetch() 向外部后端发请求（你的场景）

插件内可直接使用 `fetch()` API 向任何 HTTP 服务发请求。

```javascript
// 发送数据到 Python/Node.js 后端
async function sendToBackend(itemData) {
  try {
    const response = await fetch('http://localhost:8080/api/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(itemData),
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    Zotero.debug(`Backend error: ${error.message}`);
    throw error;
  }
}
```

> **注意**：fetch 在 Zotero（基于 Firefox）中原生可用。不需要 CORS 头。

### 后端（Python 示例）

```python
# server.py
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.get_json()
    title = data.get('title', '')
    abstract = data.get('abstract', '')
    
    # 处理逻辑...
    result = {
        'summary': f'Generated summary for: {title}',
        'tags': ['tag1', 'tag2'],
        'note': 'Generated note content...',
    }
    
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080)
```

---

## 方案二：注册 Zotero 内部 HTTP 端点（外部调用插件）

利用 Zotero 内置的 HTTP Server（端口 23119）注册自定义端点。

### 注册端点

```javascript
// 在 bootstrap.js 的 startup() 中

var myEndpoint = Zotero.Server.Endpoints["/myPlugin/process"] = function() {};
myEndpoint.prototype = {
  "supportedMethods": ["GET", "POST"],
  "supportedDataTypes": ["application/json"],
  
  "init": function(data, sendResponseCallback) {
    // data: GET query string 或 POST body
    try {
      var parsedData = JSON.parse(data);
      var result = processData(parsedData);
      sendResponseCallback(200, "application/json", JSON.stringify(result));
    } catch (e) {
      sendResponseCallback(500, "application/json", JSON.stringify({ error: e.message }));
    }
  }
};
```

### 外部调用

```bash
# 需要启用 Zotero 设置中的 "Allow other applications..."
curl -X POST http://127.0.0.1:23119/myPlugin/process \
  -H "Content-Type: application/json" \
  -d '{"itemId": 12345}'
```

### 默认端点

Zotero 内置的 Connector Server 端点：
- `/connector/ping`
- `/connector/saveItems`
- `/connector/saveSnapshot`
- `/connector/selectItems`
- `/connector/getTranslatorCode`

### 安全注意事项

- 任何本地网页都可以向 127.0.0.1:23119 发 GET/POST（但跨域限制防止读取响应）
- 建议需要认证的端点做好安全验证
- 自定义端点运行在 chrome 权限下，可执行任意 Zotero 操作

---

## 方案三：Zotero Local API（通过 HTTP 操作 Zotero 数据）

Zotero 7+ 提供本地 Web API，允许外部程序操作 Zotero 数据。

### 启用

Zotero → Preferences → Advanced → Config Editor → 搜索 `allowClient` 相关设置

或通过插件代码：
```javascript
Zotero.Prefs.set("server.localAPI.enabled", true);
```

### 使用（外部程序）

```bash
# 获取所有条目
curl http://127.0.0.1:23119/api/items

# 获取特定条目
curl http://127.0.0.1:23119/api/items/ITEMKEY

# 搜索
curl "http://127.0.0.1:23119/api/items?q=search+term"
```

### 从Zotero插件调用本地API

```javascript
// 在插件内直接操作数据，不需要通过HTTP
var items = await Zotero.Items.getAsync(ids);
```

> 插件内直接通过 JS API 操作更高效，无需走 HTTP 循环。

---

## 方案四：子进程调用

```javascript
// 调用外部可执行文件
var { Subprocess } = ChromeUtils.import("resource://gre/modules/Subprocess.jsm");

async function runExternalScript(data) {
  var proc = await Subprocess.call({
    command: '/usr/bin/python3',
    arguments: [
      '/path/to/my/script.py',
      '--input', JSON.stringify(data),
    ],
    environment: { ... },
    stderr: 'stdout',
  });
  
  var stdout = await proc.stdout.readString();
  var { exitCode } = await proc.wait();
  
  Zotero.debug(`Script exited with code ${exitCode}`);
  return JSON.parse(stdout);
}
```

---

## 推荐架构：针对你的场景

```
┌────────────────────────────────────────────────┐
│  Zotero Plugin (bootstrap.js)                  │
│                                                │
│  1. 右键条目                                    │
│  2. 获取条目数据 (Zotero.JS API)                │
│  3. fetch() → POST /api/generate               │
│  4. 接收结果                                    │
│  5. 更新条目 (item.setField + saveTx)           │
└────────────────┬───────────────────────────────┘
                 │ HTTP (localhost)
                 ▼
┌────────────────────────────────────────────────┐
│  Backend Service (Python/Node.js/etc.)         │
│  端口: 8080(或其他)                              │
│                                                │
│  接收条目数据 → 处理/生成 → 返回结果              │
└────────────────────────────────────────────────┘
```

**优势**：
- 插件代码简单，只需 fetch
- 后端可以用任何语言实现
- 逻辑分离，易于测试和迭代
- 不依赖 Zotero 内置 HTTP Server 的设置

## 信息来源

- Zotero Connector HTTP Server (官方): https://www.zotero.org/support/dev/client_coding/connector_http_server
- Zotero Server 源码: https://github.com/zotero/zotero/blob/master/chrome/content/zotero/xpcom/server.js
- Zotero Connector Server 源码: https://github.com/zotero/zotero/blob/master/chrome/content/zotero/xpcom/connector/server_connector.js
- Zotero Local API: https://www.zotero.org/support/dev/web_api/v3/local_api
- ZotSeek MCP 端点注册参考: https://github.com/introfini/ZotSeek
