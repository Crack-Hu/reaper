# Zotero JavaScript API 参考

插件可直接访问 Zotero 的 JavaScript API 来操作数据。以下是最常用的 API。

---

## 获取当前选中条目

```javascript
var zp = Zotero.getActiveZoteroPane();
var selectedItems = zp.getSelectedItems();
var item = selectedItems[0];  // 第一个选中条目
```

---

## 条目操作 (Zotero.Item)

### 创建条目

```javascript
var item = new Zotero.Item('book');          // 或 'journalArticle', 'conferencePaper' 等
item.setField('title', 'My Book Title');
item.setField('date', '2024');
item.setField('url', 'https://example.com');
item.setField('abstractNote', 'Abstract text');

// 设置作者
item.setCreators([
  {
    firstName: "John",
    lastName: "Doe",
    creatorType: "author"
  }
]);

var itemID = await item.saveTx();
```

### 获取/修改条目字段

```javascript
var item = Zotero.Items.get(itemID);

// 获取字段
var title = item.getField('title');
var abstract = item.getField('abstractNote');
var date = item.getField('date');
var url = item.getField('url');
var publication = item.getField('publicationTitle');
var publisher = item.getField('publisher');
var doi = item.getField('DOI');
var isbn = item.getField('ISBN');

// 设置字段
item.setField('abstractNote', 'New abstract');
item.setField('title', 'New Title');

// 保存
await item.saveTx();  // 独立事务
// 或在事务中
await Zotero.DB.executeTransaction(async function () {
  item.setField('abstractNote', 'New abstract');
  await item.save();
});
```

### 获取/设置创建者

```javascript
// 获取所有创建者
var creators = item.getCreators();

// 获取第一个创建者
var creator = item.getCreator(0);
// { firstName: 'John', lastName: 'Doe', creatorTypeID: 1, fieldMode: 0 }
var creatorJSON = item.getCreatorJSON(0);
// { firstName: 'John', lastName: 'Doe', creatorType: 'author' }

// 设置创建者
item.setCreators([
  { firstName: "Jane", lastName: "Smith", creatorType: "author" },
  { firstName: "Bob", lastName: "Jones", creatorType: "editor" },
]);
```

### 条目类型判断

```javascript
item.isRegularItem();    // 非附件、非笔记的常规条目
item.isNote();           // 是否是笔记
item.isAttachment();     // 是否是附件
item.isCollection();     // 是否是集合
item.isFeedItem();       // 是否是订阅条目
```

### 条目标签

```javascript
// 获取标签
var tags = item.getTags();

// 添加标签（0=手动, 1=自动）
item.addTag('my-tag', 0);

// 删除标签
item.removeTag('my-tag');
```

### 条目附件

```javascript
// 获取附件 ID 列表
var attachmentIDs = item.getAttachments();

// 获取附件对象
for (let id of attachmentIDs) {
  let attachment = Zotero.Items.get(id);
  if (attachment.attachmentContentType == 'application/pdf') {
    var text = await attachment.attachmentText;
  }
}
```

### 条目笔记

```javascript
// 获取笔记 ID 列表
var noteIDs = item.getNotes();

// 获取笔记内容
for (let id of noteIDs) {
  let note = Zotero.Items.get(id);
  let noteHTML = note.getNote();
}
```

### 创建子笔记

```javascript
var noteItem = new Zotero.Item('note');
noteItem.libraryID = item.libraryID;
noteItem.parentID = item.id;
noteItem.setNote('<p>My note content</p>');
await noteItem.saveTx();
```

### 添加附件

```javascript
// 从文件创建附件
var attachmentItem = await Zotero.Attachments.linkFromFile({
  file: '/path/to/file.pdf',
  parentItemID: item.id,
});
```

---

## 集合操作

```javascript
// 获取选中的集合
var collection = Zotero.getActiveZoteroPane().getSelectedCollection();

// 获取集合中的条目
var items = collection.getChildItems();
var itemIDs = collection.getChildItems(true); // 只返回 ID

// 创建子集合
var newCollection = new Zotero.Collection();
newCollection.name = 'My Collection';
newCollection.parentID = collection.id;
var collectionID = await newCollection.saveTx();

// 将条目添加到集合
collection.addItem(itemID);
await collection.saveTx();

// 从集合移除条目
collection.removeItem(itemID);
await collection.saveTx();
```

---

## 搜索

```javascript
var s = new Zotero.Search();
s.libraryID = Zotero.Libraries.userLibraryID;

// 添加搜索条件
s.addCondition('title', 'contains', 'keyword');
s.addCondition('tag', 'is', 'mytag');
s.addCondition('creator', 'contains', 'Smith');

// 连接模式
s.addCondition('joinMode', 'any'); // 默认 'all'

// 执行搜索
var itemIDs = await s.search();

// 获取搜索结果条目
var items = await Zotero.Items.getAsync(itemIDs);
```

### 可用的搜索字段

常用搜索字段：
`title`, `creator`, `tag`, `date`, `collection`, `collectionID`, `savedSearch`, `savedSearchID`, `itemType`, `note`, `abstractNote`, `publicationTitle`, `publisher`, `place`, `DOI`, `ISBN`, `url`, `year`, `fulltextContent`

参见: https://api.zotero.org/itemFields

---

## 数据存储与事务

```javascript
// 所有数据修改必须在事务中进行

// 方式 1: 简单保存
item.setField('title', 'New Title');
await item.saveTx();

// 方式 2: 事务中批量操作
await Zotero.DB.executeTransaction(async function () {
  let item1 = await Zotero.Items.getAsync(id1);
  let item2 = await Zotero.Items.getAsync(id2);
  item1.setField('title', 'Title 1');
  item2.setField('title', 'Title 2');
  await item1.save();
  await item2.save();
});
```

---

## 文件 I/O

```javascript
// 读取文件
var data = await Zotero.File.getContentsAsync('/path/to/file.txt');

// 写入文件
await Zotero.File.putContentsAsync('/path/to/file.txt', 'content');

// 检查文件是否存在
var exists = await Zotero.File.existsAsync('/path/to/file.txt');

// Zotero 数据目录
var dataDir = Zotero.DataDirectory.dir;
```

---

## 偏好设置

```javascript
// 读取
var value = Zotero.Prefs.get('extensions.my-plugin.optionName');
// 或直接用字符串
var value = Zotero.Prefs.get('extensions.my-plugin.optionName');

// 设置
Zotero.Prefs.set('extensions.my-plugin.optionName', 'value');

// 清除
Zotero.Prefs.clear('extensions.my-plugin.optionName');
```

### 支持的类型

```javascript
pref("extensions.my-plugin.stringPref", "default");         // 字符串
pref("extensions.my-plugin.intPref", 42);                    // 整数
pref("extensions.my-plugin.boolPref", true);                 // 布尔
pref("extensions.my-plugin.unicharPref", "unicode string");  // Unicode
```

---

## 通知系统

```javascript
// 监听数据变更
var notifierID = Zotero.Notifier.registerObserver(
  {
    notify: async function (event, type, ids, extraData) {
      // event: 'add', 'modify', 'delete', 'remove', 'move'
      // type: 'item', 'collection', 'search', 'tag', 'collection-item', 'item-tag'
      Zotero.debug(`Event: ${event}, Type: ${type}, IDs: ${ids}`);
    }
  },
  ['item', 'collection']  // 关注的数据类型
);

// 取消监听
Zotero.Notifier.unregisterObserver(notifierID);
```

---

## 调试日志

```javascript
Zotero.debug("Debug message");
Zotero.logError("Error message with stack trace");
```

日志查看：Help → Debug Output Logging → View Output

## 信息来源

- Zotero JavaScript API (官方): https://www.zotero.org/support/dev/client_coding/javascript_api
- Zotero ItemFields: https://api.zotero.org/itemFields
- Zotero 源码 (xpcom/data): https://github.com/zotero/zotero/tree/main/chrome/content/zotero/xpcom/data
