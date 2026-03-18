# User Quickstart

This file is for a normal user who does not want to read the full technical setup.

## 1. Open The Python Environment

Open `Anaconda Prompt` or a terminal that can use conda.

Activate the environment:

```powershell
conda activate for_codeX
```

## 2. Start The Program

Run these commands:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

Do not close this window while the program is running.

## 3. Open The Web Page

Open this address in your browser:

- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

You can also double-click:

- [start_program.url](/C:/Users/zzyyds/Desktop/全自动化胡说八道学术机/start_program.url)

Important:

- `start_program.url` only opens the page
- the server must already be running first

## 4. Add Papers

On the web page:

1. Click `选择论文文件`
2. Choose one or more PDF papers
3. The files will be placed into the `essay` folder automatically

You can also manually put PDFs into:

- [essay](/C:/Users/zzyyds/Desktop/全自动化胡说八道学术机/essay)

## 5. Start Reviewing

After papers appear in the list:

- select 1 paper to run a single review
- select multiple papers to run a batch review

Then set:

- `轮数`
- optional `代码目录`
- optional `运行命令`

Then click:

- `开始博弈`

## 6. See The Results

The web page will show:

- current progress
- round-by-round debate
- judge output
- final scorecard

Final user-facing reports are exported to:

- [final_report](/C:/Users/zzyyds/Desktop/全自动化胡说八道学术机/final_report)

## 7. If Something Looks Wrong

Try these first:

1. Make sure the terminal server is still running
2. Refresh the browser with `Ctrl+F5`
3. Check that your PDF is really inside `essay`
4. Check that `api_settings/llm_api_config.json` has valid API keys

## 8. If The Program Cannot Start

Install dependencies again:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe -m pip install -r requirements.txt
```

If upload fails, also run:

```powershell
D:\anaconda\envs\for_codeX\python.exe -m pip install python-multipart
```
