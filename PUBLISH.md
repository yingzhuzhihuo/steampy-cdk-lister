# 发布到 GitHub（三种方式，任选一种）

仓库已经准备好，位置：`<repo>`
推送前**务必**先跑自检：

```powershell
python scripts\check_no_secrets.py
```
必须输出 `[OK] ... 未发现登录态 / 真实 key / 绝对用户路径` 才继续。
`.gitignore` 已排除 `work/`（浏览器 profile 含登录 cookie）、`plan.json`、`results.json`、
`verified.json`、`*.xlsx`——**这些进库等于泄露账号**。

---

## 方式 A：用 GitHub API 上传（不需要装 git）

需要你在 https://github.com/settings/tokens 建一个 **Fine-grained token**：
- Repository access：`All repositories` 或指定；新建仓库需要 `Administration: Read and write`
- 权限：`Contents: Read and write`、`Administration: Read and write`

然后把 token 设成临时环境变量（不要写进任何文件）：

```powershell
$env:GH_TOKEN = "github_pat_xxx"
python publish_api.py --owner <你的用户名> --repo steampy-cdk-lister
Remove-Item Env:\GH_TOKEN
```

`publish_api.py` 会：建仓库 → 按目录逐个上传文件 → 打印仓库地址。

---

## 方式 B：本机装 git 自己推

```powershell
winget install --id Git.Git -e
# 重开一个终端后：
cd <repo>
git init -b main
git add .
git status            # 再确认一遍没有 work/ 、没有 xlsx
git commit -m "feat: steampy CDKey bulk lister"
```

在 GitHub 网页建一个空仓库（不要勾 README），然后：

```powershell
git remote add origin https://github.com/<你>/steampy-cdk-lister.git
git push -u origin main
```

首次推送会弹浏览器登录，或改用 token：
`git remote add origin https://<user>:<token>@github.com/<user>/steampy-cdk-lister.git`

---

## 方式 C：网页拖拽上传

1. 生成压缩包（已排除 profile）：

```powershell
Compress-Archive -Path <repo>\* `
  -DestinationPath $env:TEMP\steampy-cdk-lister.zip -Force
```

2. 打开 https://github.com/new 建空仓库
3. 仓库页 → `Add file` → `Upload files` → 解压后把文件拖进去 → Commit

注意：`.gitignore` 是隐藏文件，网页上传仍要勾选显示隐藏文件，否则会漏掉。

---

## 发布后建议

- 仓库 Description 用一句话：`Batch-list Steam CDKeys on SteamPY seller center, priced by market top price, rate-limit aware.`
- Topics：`steampy` `cdkey` `playwright` `automation` `dsh-skill`
- 想加 CI 就跑：`python scripts/check_no_secrets.py`（每次 push 检查是否误传凭据）
- 别把 `work/` 加进仓库；如果已经提交过，用 `git filter-repo` 清历史并**立即重新登录**让旧 token 失效
