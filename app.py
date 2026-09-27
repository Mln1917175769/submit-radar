import re
import csv
import io
import requests
import streamlit as st

st.set_page_config(page_title="提交雷达", layout="wide")

GITHUB_RE = re.compile(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)")
VIDEO_DOMAINS = [
    "bilibili.com", "youtube.com", "youtu.be", "v.qq.com",
    "pan.baidu.com", "aliyundrive.com", "123pan.com"
]
BAD_WORDS = ["test", "demo", "新建文件夹", "未命名", "untitled", "aaa", "123"]


def extract_entries(text):
    entries = []
    for line in text.splitlines():
        if "github.com" not in line:
            continue
        name_match = re.search(r"@([\u4e00-\u9fa5A-Za-z0-9_-]+)", line)
        name = name_match.group(1) if name_match else "未识别"
        repo_match = GITHUB_RE.search(line)
        if repo_match:
            owner = repo_match.group(1)
            repo = repo_match.group(2).replace(".git", "")
            entries.append({
                "同学": name,
                "owner": owner,
                "repo": repo,
                "链接": repo_match.group(0)
            })
    unique = {}
    for e in entries:
        unique[(e["owner"], e["repo"])] = e
    return list(unique.values())


def extract_videos(text):
    urls = re.findall(r"https?://[^\s]+", text)
    videos = []
    for url in urls:
        if "github.com" in url:
            continue
        if any(domain in url for domain in VIDEO_DOMAINS):
            videos.append(url)
    return list(set(videos))


def check_repo(owner, repo, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    result = {
        "存在": False,
        "私有": None,
        "README": False,
        "默认分支": "",
        "问题": []
    }

    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        r = requests.get(api, headers=headers, timeout=10)
    except Exception:
        result["问题"].append("网络请求失败")
        return result

    if r.status_code == 200:
        data = r.json()
        result["存在"] = True
        result["私有"] = data.get("private")
        result["默认分支"] = data.get("default_branch", "main")

        readme_api = f"{api}/readme"
        rr = requests.get(readme_api, headers=headers, timeout=10)
        result["README"] = rr.status_code == 200

    elif r.status_code == 404:
        result["问题"].append("仓库不存在或私有不可见")
    elif r.status_code in (401, 403):
        result["问题"].append("令牌无效或权限不足")
    else:
        result["问题"].append(f"接口返回 {r.status_code}")

    return result


def score_repo_name(repo):
    score = 100
    reasons = []
    lower = repo.lower()

    for word in BAD_WORDS:
        if word in lower:
            score -= 40
            reasons.append(f"含随意词“{word}”")
            break

    if len(repo) < 4:
        score -= 20
        reasons.append("名称过短")

    if re.search(r"[\u4e00-\u9fa5]", repo):
        score -= 10
        reasons.append("含中文")

    if not re.match(r"^[A-Za-z0-9._-]+$", repo):
        score -= 20
        reasons.append("含特殊字符")

    if score >= 80:
        reasons.append("名称规范")

    return score, "；".join(reasons)


def make_message(row, deadline):
    if row["状态"] == "通过":
        return ""
    return f"@{row['同学']} 你的项目提交需要修正：{row['问题']}。请在 {deadline} 前处理。仓库：{row['链接']}"


st.title("提交雷达")
st.caption("群作业与代码提交合规检查器")

with st.sidebar:
    st.header("检查设置")
    token = st.text_input("GitHub 令牌（可选，用于检查私有仓库）", type="password")
    deadline = st.text_input("截止时间", "今天 18:00")
    uploaded = st.file_uploader("上传群聊文本文件", type=["txt", "md", "csv"])

default_text = ""
if uploaded is not None:
    default_text = uploaded.read().decode("utf-8", errors="ignore")

text = st.text_area("粘贴群聊记录", value=default_text, height=220)

run = st.button("开始检查", type="primary")

if run and text:
    entries = extract_entries(text)
    videos = extract_videos(text)

    if not entries:
        st.warning("没有识别到 GitHub 仓库链接，请检查群聊内容。")
    else:
        rows = []
        for e in entries:
            info = check_repo(e["owner"], e["repo"], token)
            name_score, name_reason = score_repo_name(e["repo"])

            problems = []
            if not info["存在"]:
                problems.append("仓库不存在或不可访问")
            else:
                if info["私有"] and not token:
                    problems.append("私有仓库，未提供令牌")
                if not info["README"]:
                    problems.append("缺少 README.md")

            if name_score < 80:
                problems.append("项目名：" + name_reason)

            status = "通过" if not problems else "需修正"

            row = {
                "同学": e["同学"],
                "仓库": f"{e['owner']}/{e['repo']}",
                "链接": e["链接"],
                "仓库存在": info["存在"],
                "私有": info["私有"],
                "README": info["README"],
                "项目名得分": name_score,
                "项目名建议": name_reason,
                "问题": "；".join(problems) if problems else "无",
                "状态": status
            }
            row["催办话术"] = make_message(row, deadline)
            rows.append(row)

        st.subheader("提交检查总览")
        st.dataframe(rows, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("状态统计")
            counts = {}
            for row in rows:
                counts[row["状态"]] = counts.get(row["状态"], 0) + 1
            st.bar_chart(counts)
        with col2:
            st.subheader("识别到的演示视频")
            if videos:
                for v in videos:
                    st.write(v)
            else:
                st.write("未识别到演示视频链接")

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        csv_data = output.getvalue().encode("utf-8-sig")

        st.download_button(
            "下载检查报告",
            csv_data,
            "提交检查报告.csv",
            "text/csv"
        )