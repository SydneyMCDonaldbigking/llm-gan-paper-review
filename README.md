# 使用说明

现在这个项目已经整理成 3 个主要文件夹：

- `program`
  所有代码、前端、后端、运行产物都在这里。
- `essay`
  把要审稿的论文 PDF 放到这里。
- `api_settings`
  把模型 API 配置放到这里，目前使用的是 `llm_api_config.json`。

最简单的用法：

1. 把论文放进 `essay/`
2. 检查 `api_settings/llm_api_config.json`
3. 进入 `program/`
4. 启动网页界面

```powershell
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

然后打开：

```text
http://127.0.0.1:8000/
```

如果想命令行直接跑：

```powershell
D:\anaconda\envs\for_codeX\python.exe program\run_review.py --paper "CUFE at SemEval-2016.pdf" --rounds 1
```
