# 使用概述

## 简介
百度网盘核心API现已全面兼容MCP协议。涵盖用户信息、获取文件信息、文件上传、文件管理、文件搜索等。 开发者仅需简单配置，即可快速接入百度网盘服务，实现文件上传、文件管理等能力，大幅降低开发者调用网盘服务门槛，显著提升开发者的开发效率。

## 功能介绍

| 功能名称         | 功能描述         | 功能说明                                                                 |
|------------------|------------------|--------------------------------------------------------------------------|
| [file_list](###基础文件信息-获取文件列表) | 基础文件信息-获取文件列表 | 获取用户网盘中指定目录下的文件列表。                                   |
| [file_doc_list](###基础文件信息-获取文档列表)    | 基础文件信息-获取文档列表 | 获取用户指定目录下的文档列表。                                         |
| [file_image_list](###基础文件信息-获取图片列表)  | 基础文件信息-获取图片列表 | 获取用户指定目录下的图片列表。                                         |
| [file_video_list](###基础文件信息-获取视频列表)  | 基础文件信息-获取视频列表 | 获取用户指定目录下的视频列表。                                         |
| [file_meta](###基础文件信息-获取文件详细信息)  | 基础文件信息-获取文件详细信息 | 通过文件ID获取网盘文件的详细信息。                                         |
| [make_dir](###文件管理-创建文件夹)         | 文件管理-创建文件夹       | 创建文件夹。                                                            |
| [file_copy](###文件管理-复制)        | 文件管理-复制           | 对指定的文件进行复制操作。                                             |
| [file_del](###文件管理-删除)         | 文件管理-删除           | 对指定的文件进行删除操作。                                             |
| [file_move](###文件管理-移动)        | 文件管理-移动           | 对指定的文件进行移动操作。                                             |
| [file_rename](###文件管理-重命名)      | 文件管理-重命名         | 对指定的文件进行重命名操作。                                           |
| [file_upload_stdio](###文件上传-上传本地文件)| 文件上传-上传本地文件 | 将用户本地文件上传存储在网盘的云端文件。</br>**因需对本地文件读取，上传本地文件仅支持stdio模式。** |
| [file_upload_by_url](###文件上传-通过URL上传)| 文件上传-通过URL上传 | 通过文件链接上传文件到网盘。 |
| [file_upload_by_url](###文件上传-通过文本上传)| 文件上传-通过文本上传 | 通过文本内容上传文件到网盘。 |
| [file_keyword_search](###文件搜索-文件名检索)      | 文件搜索-文件名检索  | 网盘文件名关键词搜索。获取用户指定目录下，包含指定关键字的文件列表。    |
| [file_semantics_search](###文件搜索-文件语义检索)      | 文件搜索-文件语义检索  | 网盘文件语义检索，支持自然语言描述下的复杂query搜索网盘中的文件。    |
| [file_sharelink_set](###文件分享-创建分享链接)      | 文件分享-创建分享链接  | 创建文件分享链接。    |
| [user_info](###用户基础信息-获取已鉴权用户信息)        | 用户基础信息-获取已鉴权用户信息 | 获取用户的基本信息。                               |
| [get_quota](###用户基础信息-获取网盘容量信息)        | 用户基础信息-获取网盘容量信息 | 获取用户的网盘空间的使用情况。     

### 基础文件信息-获取文件列表
```
 * 说明：获取用户网盘中指定目录下的文件列表，不限定文件类型。
 * 输入：
   * dir：目录名称，以 / 开头的绝对路径，默认为 /。路径包含中文时需要 UrlEncode 编码 (斜杠 / 也需要编码)
   * page：列表页码，从 1 开始， 如果不指定页码，则为不分页模式，返回所有的结果。如果指定 page 参数，则按修改时间倒序排列，默认为1从第一页拉取，拉取更多则依次传2、3、4等
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```

### 基础文件信息-获取文档列表
```
 * 说明：获取用户指定目录下的文档列表。
 * 输入：
   * dir：目录名称，以 / 开头的绝对路径，默认为 /。路径包含中文时需要 UrlEncode 编码 (斜杠 / 也需要编码)
   * page：列表页码，从 1 开始， 如果不指定页码，则为不分页模式，返回所有的结果。如果指定 page 参数，则按修改时间倒序排列，默认为1从第一页拉取，拉取更多则依次传2、3、4等
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```

### 基础文件信息-获取图片列表
```
 * 说明：获取用户指定目录下的图片列表。
 * 输入：
   * dir：目录名称，以 / 开头的绝对路径，默认为 /。路径包含中文时需要 UrlEncode 编码 (斜杠 / 也需要编码)
   * page：列表页码，从 1 开始， 如果不指定页码，则为不分页模式，返回所有的结果。如果指定 page 参数，则按修改时间倒序排列，默认为1从第一页拉取，拉取更多则依次传2、3、4等
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```

### 基础文件信息-获取视频列表
```
 * 说明：获取用户指定目录下的视频列表。
 * 输入：
   * dir：目录名称，以 / 开头的绝对路径，默认为 /。路径包含中文时需要 UrlEncode 编码 (斜杠 / 也需要编码)
   * page：列表页码，从 1 开始， 如果不指定页码，则为不分页模式，返回所有的结果。如果指定 page 参数，则按修改时间倒序排列，默认为1从第一页拉取，拉取更多则依次传2、3、4等
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```
### 基础文件信息-获取文件详细信息
```
 * 说明：通过文件ID获取网盘文件的详细信息。
 * 输入：
   * fsids：文件ID列表，支持批量查询，最大数量10个。如[111, 222, 333]
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```
### 文件管理-创建文件夹
```
 * 说明：创建文件夹。
 * 输入：
   * rtype：重命名策略，默认为1。0-不重命名（返回冲突），1-path冲突则重命名，2-path冲突且block_list不同才重命名，4-冲突则覆盖。
   * path：创建文件夹的绝对路径，需要urlencode
 * 输出：
   * fsid：网盘文件ID
   * category：分类类型, 6 文件夹
   * path：上传后使用的文件绝对路径
   * ctime：文件创建时间
   * mtime：文件修改时间
   * isdir：是否目录，0 文件、1 目录
```

### 文件管理-复制
```
 * 说明：对指定的文件进行复制操作。
 * 输入：
   * async：是否同步：0同步，1自适应，2异步。默认为1
   * ondup：全局ondup,遇到重复文件的处理策略, fail(直接返回失败)、newcopy(重命名文件)、overwrite（覆盖文件）、skip（跳过），默认为newcopy
   * filelist（json array）：示例：[{"path":"/test/123456.docx","dest":"/test/abc","newname":"11223.docx"}]
     * path：原文件绝对路径
     * dest：目标目录
     * newname：目标文件名
 * 输出：
   * taskid：异步任务id, 当async=2时返回
```

### 文件管理-删除
```
 * 说明：对指定的文件进行删除操作。
 * 输入：
   * async：是否同步：0同步，1自适应，2异步。默认为1
   * ondup：全局ondup,遇到重复文件的处理策略, fail(直接返回失败)、newcopy(重命名文件)、overwrite（覆盖文件）、skip（跳过），默认为newcopy
   * filelist（json array）：要删除文件的绝对路径，字符串数组，示例：["/test/123456.docx"]
 * 输出：
   * taskid：异步任务id, 当async=2时返回
```

### 文件管理-移动
```
 * 说明：用于对指定的文件进行移动操作。
 * 输入：
   * async：0 同步，1 自适应，2 异步
   * ondup：全局ondup,遇到重复文件的处理策略, fail(默认，直接返回失败)、newcopy(重命名文件)、overwrite、skip
   * filelist（json array）：示例：[{"path":"/test/123456.docx","dest":"/test/abc","newname":"11223.docx"}]
     * path：原文件绝对路径
     * dest：目标目录
     * newname：目标文件名
 * 输出：
   * taskid：异步任务id, 当async=2时返回
   * info（array）：文件信息
```

### 文件管理-重命名
```
 * 说明：对指定的文件进行重命名操作。
 * 输入：
   * async：是否同步：0同步，1自适应，2异步。默认为1
   * ondup：全局ondup，遇到重复文件的处理策略, fail(直接返回失败)、newcopy(重命名文件)、overwrite（覆盖文件）、skip（跳过），默认为newcopy
   * filelist（json array）：json串数组，示例：[{"path":"/test/123456.docx","newname":"123.docx"}]
     * path：原文件绝对路径
     * newname：新文件名
 * 输出：
   * taskid：异步任务id, 当async=2时返回
   * info（array）：文件信息
```

### 文件上传-上传本地文件
```
 * 说明：用于将用户本地文件上传存储在网盘的云端文件。因需要对本地文件进行读取，上传工具仅支持stdio模式。
 * 输入：
   * local_file_path：本地文件路径
   * remote_path：（可选参数）网盘存储路径，必须以/开头。如不指定，将默认上传到"/来自：mcp_server"目录下
 * 输出：
   * filename：文件名
   * size：文件size，单位字节
   * remote_path：文件在网盘里的路径
   * fs_id：文件fsid
   * status：上传是否成功，成功：success，失败 error
   * message：提示信息
```

### 文件上传-通过URL上传
```
 * 说明：通过文件链接上传文件到网盘。
 * 输入：
   * url：需要上传到网盘的文件可下载链接URL
   * dir：上传到网盘的文件夹路径，如根路径"/"。用户未指定上传目录时，默认上传至“/来自：mcp_server"
   * filename：保存到网盘的文件名。用户未指定文件名时，默认使用URL中提取的文件名加上mcp后缀标识
 * 输出：
   * fsid：网盘文件ID
   * path：文件全路径
   * md5：文件MD5值
   * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
   * size：文件大小，单位字节
   * filename：文件名
```

### 文件上传-通过文本上传
```
 * 说明：通过文本内容上传文件到网盘。
 * 输入：
   * content：需要上传的文件内容。比如对于文本内容，则填写文本字符串。文本长度不超过2万字
   * dir：上传到网盘的文件夹路径，如根路径"/"。用户未指定上传目录时，默认上传至“/来自：mcp_server"
   * filename：保存到网盘的文件名。用户未指定文件名时，默认保存为docx格式文件
 * 输出：
   * fsid：网盘文件ID
   * path：文件全路径
   * md5：文件MD5值
   * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
   * size：文件大小，单位字节
   * filename：文件名
```

### 文件搜索-文件名检索
```
 * 说明：网盘文件名关键词搜索。获取用户指定目录下，包含指定关键字的文件列表。
 * 输入：
   * dir：搜索目录，默认为根目录"/"
   * key：文件名搜索的关键字
   * page：列表页码，从 1 开始， 如果不指定页码，则为不分页模式，返回所有的结果。如果指定 page 参数，默认为1从第一页拉取，拉取更多则依次传2、3、4等
   * num：每页条目数，跟page参数共用，默认为50
 * 输出：
   * list 文件信息列表
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
```

### 文件搜索-文件语义检索
```
 * 说明：网盘文件语义检索，支持自然语言描述下的复杂query搜索网盘中的文件。
 * 输入：
   * dir：指定搜索目录的路径，默认在网盘根目录"/"下搜索
   * query：用于网盘文件搜索的自然语言描述，可输入搜索需要的文件名、文件类型、文件特性、文件大小、文件创建时间等
 * 输出：
   * list（array）：文件信息列表。包含以下信息：
     * fsid：网盘文件ID
     * path：文件全路径
     * md5：文件MD5值
     * category：文件类型，1：视频 ；2：音频 ；3：图片 ；4：文档； 5：APP； 6：其他； 7：bt种子
     * size：文件大小，单位字节
     * filename：文件名
     * content：文件分段内容，如文档内容、视频字幕、音频文稿，若未生产返回空
     * thumbnail：图片缩略图地址
     * abstract：文件内容摘要，若未生产返回空
```

### 文件分享-创建分享链接
```
 * 说明：创建文件分享链接。
 * 输入：
   * fsid_list：分享文件ID列表，必须为严格的JSON数组格式（注意：数组本身是字符串类型，需包含双引号）。示例：'[\"111\",\"222\"]'（注意元素是字符串且用双引号包裹）
   * period：分享有效期，单位天。默认7天
   * pwd：分享密码，长度4位，数字+小写字母组成。默认值1234
 * 输出：
   * link：分享链接
   * period：分享有效期
   * pwd：分享密码
   * short_url：分享短链
```

### 用户基础信息-获取已鉴权用户信息
```
 * 说明：获取用户的基本信息，包括账号、头像地址、会员类型等。
 * 输入：无需额外参数
 * 输出：
   * avatar_url：头像地址
   * vip_type：会员类型
   * uk：用户ID
```

### 用户基础信息-获取网盘容量信息
```
 * 说明：获取用户的网盘空间的使用情况，包括总空间大小，已用空间和剩余可用空间情况。
 * 输入：无需额外参数
 * 输出：
   * total：总空间大小，单位B
   * expire：7天内是否有容量到期
   * used：已使用大小，单位B
   * free：免费容量，单位B
```

# 使用准备

## 简介

### 一、企业开发者接入
需要完成基本流程才能使用开放平台的各种能力以及服务，通用的操作流程如下图所示：
![image.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/image_ab3c426.png)

### 二、个人用户（限时体验）
> **注意：百度网盘开放平台目前仅限企业开发者注册调用，本模块提供的密钥信息仅供测试体验，将不定期变更密钥，请勿用于正式环境。**
> 正式使用请申请成为企业开发者 【[点击申请企业认证](https://pan.baidu.com/union/apply?)】

<img src="https://bce.bdstatic.com/doc/xpan-open-platform/doc/image_06952d3.png" width="400" height="46" alt="图片描述">

## 服务密钥（AK）获取流程

### 一、企业开发者

#### 1. 注册登录百度账号
在使用服务之前，开发者需要在百度网盘开放平台注册百度账号，具体流程请参考【[注册登录百度账号](https://pan.baidu.com/union/doc/Ll0ffxg47)】。
#### 2. 实名认证
账号注册完后，需要完成实名认证才能享受网盘的各类能力和服务，具体流程请参考【[实名认证](https://pan.baidu.com/union/doc/ll0g1s7jb)】。
#### 3. 创建应用
完成实名认证后，开发者需要先在开放平台的控制台中完成应用的创建以获得关键接入信息，具体流程请参考【[创建应用](https://pan.baidu.com/union/doc/fl0hhnulu)】。
#### 4. 获取服务密钥（AK）
目前开放平台的服务均基于百度OAuth体系构建，如果需要接入开放平台的服务，需要先为您的应用接入授权，获取Access Token，具体流程请参考【[接入授权](https://pan.baidu.com/union/doc/ol0rsap9s)】。

### 二、个人用户（限时体验）

#### 1. 注册登录百度账号
在使用服务之前，开发者需要注册百度账号，具体流程请参考【[注册登录百度账号](https://pan.baidu.com/union/doc/Ll0ffxg47)】。

#### 2. 获取服务密钥（AK）
目前开放平台的服务均基于百度OAuth体系构建，如果需要接入开放平台的服务，需要先为您的账号接入授权，获取Access Token。具体流程如下：
#### 2.1 发起授权请求
【[点击此处发起授权请求](https://openapi.baidu.com/oauth/2.0/authorize?response_type=token&client_id=QHOuRXiepJBMjtk0esLhrPoNlQyYd0mF&redirect_uri=oob&scope=basic,netdisk)】
> ![0c94ed02a4e34867cd46559dc49aa17e.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/0c94ed02a4e34867cd46559dc49aa17e_0c94ed0.png)

#### 2.2 获取Access Token
点击上述链接后，跳转至授权页面，用户点击“授权”按钮后跳转至Access Token链接。复制链接中Access Token部分即可。

- **第一步：账号授权**
><img src="https://bce.bdstatic.com/doc/xpan-open-platform/doc/e1a8ab6bc0bde523f10929b5710ac83f_e1a8ab6.png" width="430" height="230" alt="图片描述">

- **第二步：复制链接中Access Token**
> ![719b2277a7738391ab6451ac96345cd3.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/719b2277a7738391ab6451ac96345cd3_719b227.png)


**3. 授权管理**

如您需要进行应用解绑，可在 【[授权管理](https://passport.baidu.com/v6/appAuthority)】 管理网盘MCP Server的授权，对授权过的应用做权限“设置”、“解除关联”等操作。
><img src="https://bce.bdstatic.com/doc/xpan-open-platform/doc/cceba5f3c08f76b65491e6eb5fd4b873_cceba5f.png" width="430" height="210" alt="图片描述">

## 使用百度网盘MCP Server
获取到Access Token 凭证就可以调用网盘MCP Server，访问用户信息以及授权资源了。

# 快速开始

## 简介
凡是支持MCP协议的平台（如Claude、Cursor、Cline）均能够简单接入百度网盘MCP server。百度网盘提供了SSE和Python两种接入方式供用户选择。其中，上传功能仅可通过Python进行本地接入，其余功能支持通过SSE方式接入。</br>
以Cursor平台接入为例，在进行接入操作前，建议用户先安装并使用最新版本的Cursor客户端。
## 通过SSE接入
> 注意：上传工具需要对本地文件进行读取，SSE模式不包含上传工具，如需使用上传请使用stdio模式。

### 一、Cursor配置
1. 打开Cursor配置，在MCP中添加MCP Server </br>
> ![cf3bfc01f081cb1cadf06fbac4a1a9f6.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/cf3bfc01f081cb1cadf06fbac4a1a9f6_cf3bfc0.png)

2. 在mcp.json配置文件中添加如下内容后保存
> 注意：请先完成网盘开放平台用户鉴权，获取Access Token。 参考[【使用准备】](https://pan.baidu.com/union/doc/Wm9sl0i0j)
```
{
  "mcpServers": {
    "baidu-netdisk": {
      "url": "https://mcp-pan.baidu.com/sse?access_token=您的AccessToken"
    }
  }
}
```

3. 回到配置，可在MCP Servers列表中查看百度网盘MCP Server启用状态</br>
> ![image.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/image_a2379f8.png)

### 二、在Cursor中使用
Cursor会话选择Agent交互模式即可开始使用，可参考案例：
> 例：帮我新建一个文件夹，名称为AIGC调研文档，并把网盘中的AIGC相关文件复制到这个文件夹下
> 
![631caf5658b0a4f203c2491d783483f9.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/631caf5658b0a4f203c2491d783483f9_631caf5.png)

## 通过Stdio接入

### 一、Stdio源码获取
本地文件上传到百度网盘云端文件可通过Stdio源码接入，Stdio模式的Python SDK详见
[【Python SDK-Stdio模式】](https://pan.baidu.com/union/doc/Cm9si7mfw)

### 二、Cursor配置
1. 打开Cursor配置，在MCP中添加MCP Server</br>
> ![cf3bfc01f081cb1cadf06fbac4a1a9f6.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/cf3bfc01f081cb1cadf06fbac4a1a9f6_cf3bfc0.png)

2. 在mcp.json配置文件中添加如下内容后保存
> 注意：请先完成网盘开放平台用户鉴权，获取Access Token。 参考[【使用准备】](https://pan.baidu.com/union/doc/Wm9sl0i0j)
```
MAC/Linux：
{
  "mcpServers": {
    "baidu-netdisk-local-uploader": {
      "command": "uv的绝对路径，通过shell命令获取，如/Users/netdisk/.local/bin/uv",
      "args": [
          "--directory",
          "netdisk.py所在目录的绝对路径，如/Users/netdisk/mcp/netdisk-mcp-server-stdio",
          "run",
          "netdisk.py"
      ],
      "env": {
        "BAIDU_NETDISK_ACCESS_TOKEN": "<YOUR_ACCESS_TOKEN>"
      }
    }
  }
}
```
```
Windows：
{
    "mcpServers": {
        "baidu-netdisk-local-uploader": {
            "command": "uv的绝对路径，通过shell命令获取，如/Users/netdisk/.local/bin/uv",
            "args": [
                "--directory",
                "netdisk.py所在目录的绝对路径，如C:\\ABSOLUTE\\PATH\\TO\\PARENT\\FOLDER\\netdisk-mcp-server-stdio",
                "run",
                "netdisk.py"
            ],
            "env": {
                "BAIDU_NETDISK_ACCESS_TOKEN": "<YOUR_ACCESS_TOKEN>"
            }
        }
    }
}
```
3. 回到配置，可在MCP Servers列表中查看百度网盘MCP Server启用状态</br>
> ![fabd05ea8b1040ac4333b3bfb50d1636.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/fabd05ea8b1040ac4333b3bfb50d1636_fabd05e.png)

### 三、在Cursor中使用
Cursor会话选择Agent交互模式即可开始使用。
> 例：指定本地文件上传到网盘（未指定上传目录，默认上传至“/来自：mcp_server”）
> 
> ![778f5389dad0a7c513b2ae005d56d1c6.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/778f5389dad0a7c513b2ae005d56d1c6_778f538.png)

> 例：指定本地文件上传到网盘指定目录下
> 
> ![f27e63183ac344300c9b76f4bff844d7.png](https://bce.bdstatic.com/doc/xpan-open-platform/doc/f27e63183ac344300c9b76f4bff844d7_f27e631.png)

## 通过MCP客户端接入
我们提供网盘MCP Server工具集的MCP Client调用示例Demo（Python语言），可以为您提供客户端调用网盘MCP Server参考。接入参考[【MCP Client Demo】](https://pan.baidu.com/union/doc/Vm9sjsnat)