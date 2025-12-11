"""
Sales Report App - Streamlit Application
営業報告アプリ - 音声/テキストから営業情報を抽出してKintoneに登録
"""

import os
import json
from datetime import datetime, date
from pathlib import Path

import streamlit as st
import requests
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-pro"

# Kintone API Configuration - 営業報告アプリ
KINTONE_SUBDOMAIN = os.getenv("KINTONE_SUBDOMAIN")
KINTONE_APP_ID = os.getenv("KINTONE_APP_ID")
KINTONE_API_TOKEN = os.getenv("KINTONE_API_TOKEN")

# Kintone API Configuration - 取引先アプリ
KINTONE_CLIENT_APP_ID = os.getenv("KINTONE_CLIENT_APP_ID")
KINTONE_CLIENT_API_TOKEN = os.getenv("KINTONE_CLIENT_API_TOKEN")

# Directory for saving audio files
SAVED_AUDIO_DIR = Path("./saved_audio")

# =============================================================================
# MASTER DATA - 選択肢リスト
# =============================================================================

# 新規営業件名・次回営業件名の選択肢
SALES_ACTIVITY_OPTIONS = [
    "架電、メール",
    "アポ架電（担当者通電）",
    "初回訪問",
    "提案（担当者訪問）",
    "提案（見積書提出）",
    "提案（決裁者訪問・プレゼン）",
    "合意後訪問（商談）",
    "訪問（公示前）",
    "公示対応（提案書提出）",
    "公示対応（プレゼン参加）",
    "公示対応（入札・開封）",
    "合意後訪問（公示）",
]

# 対応者の選択肢
STAFF_OPTIONS = [
    "水野 邦彦",
    "杉山 拓真",
    "一條 祐輔",
    "堀越 隆太郎",
    "矢部 昌子",
    "鈴木 沙耶佳",
    "井﨑 優",
    "鈴木 智朗",
    "中村 紀夫",
]

# 対応者名 → Kintoneユーザーコード（メールアドレス）のマッピング
STAFF_CODE_MAP = {
    "水野 邦彦": "mizuno.k@kids-21.co.jp",
    "杉山 拓真": "sugiyama.t@kids-21.co.jp",
    "一條 祐輔": "ichijo.y@kids-21.co.jp",
    "堀越 隆太郎": "horikoshi.r@kids-21.co.jp",
    "矢部 昌子": "yabe.m@kids-21.co.jp",
    "鈴木 沙耶佳": "suzuki.sayaka@kids-21.co.jp",
    "井﨑 優": "izaki.m@kids-21.co.jp",
    "鈴木 智朗": "suzuki.tomoaki@kids-21.co.jp",
    "中村 紀夫": "nakamura.norio@kids-21.co.jp",
}

# =============================================================================
# INITIALIZATION
# =============================================================================

def init_directories():
    """Create necessary directories if they don't exist."""
    SAVED_AUDIO_DIR.mkdir(exist_ok=True)


def init_gemini():
    """Initialize Gemini API client."""
    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")
        return False
    genai.configure(api_key=GEMINI_API_KEY)
    return True


# =============================================================================
# KINTONE - 取引先検索
# =============================================================================

def search_clients(keyword: str) -> list:
    """Search clients from Kintone by name."""
    if not KINTONE_CLIENT_APP_ID or not KINTONE_CLIENT_API_TOKEN:
        st.error("取引先アプリの設定が不足しています。.envを確認してください。")
        return []
    
    url = f"https://{KINTONE_SUBDOMAIN}.cybozu.com/k/v1/records.json"
    headers = {
        "X-Cybozu-API-Token": KINTONE_CLIENT_API_TOKEN,
    }
    
    # クエリパラメータ（URLエンコードされる）
    params = {
        "app": KINTONE_CLIENT_APP_ID,
        "query": f'取引先名 like "{keyword}" limit 20',
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        # デバッグ情報
        if response.status_code != 200:
            st.error(f"API応答: {response.status_code}")
            st.code(response.text, language="json")
            return []
        
        records = response.json().get("records", [])
        
        # 取引先IDフィールドの値と名前のリストを返す
        # ルックアップには取引先IDフィールドの値を使う（レコード番号$idではない）
        return [
            {
                "id": rec.get("取引先ID", {}).get("value", rec["$id"]["value"]),
                "record_id": rec["$id"]["value"],
                "name": rec.get("取引先名", {}).get("value", "不明")
            }
            for rec in records
        ]
    except requests.exceptions.RequestException as e:
        st.error(f"取引先検索エラー: {e}")
        return []



# =============================================================================
# GEMINI AI PROCESSING
# =============================================================================

def get_extraction_prompt():
    """Return the system prompt for JSON extraction."""
    return """
あなたは営業報告書作成のエキスパートAIです。
入力された商談の文字起こしやメモ情報から、以下の4つのフィールドを抽出し、厳密なJSON形式で出力してください。

## 前提条件
- **自社名**: 株式会社キッズコーポレーション（通称：キッズ、キッズさん 等）
- 自社の情報は「競合情報」には含めず、必要な場合のみ「商談内容」に含めてください。
- 入力テキストには誤字・脱字（音声認識エラー）が含まれる可能性があります。文脈から正しい用語や会社名を推測して補完してください。

## 出力フィールド定義と抽出ルール

### 1. current_issues（現在の課題・問題点）
- **内容**: クライアントが抱える悩み、困りごと。
- **文字数目安**: 100〜200文字
- **抽出対象例**:
  - 園児が集まらない、利用率が低い
  - 保育士の反発、採用難、退職
  - 委託会社と連絡が取れない、対応が悪い
  - 予算超過、コスト高、運営の手間
  - 制度（企業主導型・児童育成協会など）への理解不足、監査対応の負担
  - 預かり制限の実施など

### 2. competitor_market_info（競合・マーケット情報）
- **内容**: 競合他社の動向やマーケット情報。**自社（キッズコーポレーション）の情報は絶対に含めないでください。**
- **文字数目安**: 100〜200文字
- **抽出対象例**: 他社の値上げ、訪問頻度、単価、見積額、撤退の噂、採用状況など。
- **競合他社リスト（参考）**:
  - アンフィニ、IQキッズ、OZcompany、SOUキッズケア（スクルド、アピカル）、アードチャイルドケア、さくらグループ、トットメイト、ニチイ学館（ニチイキッズ）、ピジョンハーツ、ふれ愛チャイルド、ライクキッズ、tomorrowcompany、アイグラン、タスク・フォースミテラ、テノ・ホールディングス、テンダーラビングケアサービス、はな保育、パワフルケア、プライムツーワン、ポピンズエデュケア、マミーズファミリー、メディフェア、明日香、ten、その他同業他社
  ※リストになくても文脈から競合と判断できる場合は抽出すること。

### 3. meeting_summary（商談内容）
- **内容**: 上記「1.現在の課題」「2.競合情報」で**抽出した内容を除いた**、商談の事実と要約。重複を避けてください。
- **文字数目安**: 100〜300文字
- **構成**:
  1. **訪問の種類の明記**:（例：初回訪問、飛び込み、定期訪問、提案書提出、見積提出など）
  2. **実施内容と反応**: 何を説明し、どういう反応だったか（自社説明の詳細は省き、事実のみ）。
  3. **園の基本情報（見積必須情報）**: 園児数（年齢別）、先生の人数（雇用形態別）、駐車場の契約形態、園の種別（認可、企業主導型など）があれば必ず記載。
- **記述例**: 「初回飛び込み訪問を実施。現状の委託先に不満があり、見積提出の依頼を受けた。園児数は0歳1名、1歳2名、2歳5名。駐車場は法人契約あり。」

### 4. next_proposal（次回提案内容）
- **内容**: 次に行うべきアクション。具体的かつ端的に。
- **文字数目安**: 50文字以内
- **記述例**:
  - 定期的に連絡を行う
  - 必要事項には随時対応する
  - 状況わかり次第すぐにメールを送る
  - 見積書・提案書を提出する
  - ○月○日に再訪問する

## 出力形式:
必ず以下のJSON形式のみを出力してください。説明や前置きは不要です。
```json
{
    "商談内容": "商談の要約",
    "現在の課題・問題点": "課題や問題点",
    "競合・マーケット情報": "競合情報",
    "次回提案内容": "次回の提案内容"
}
```

情報が不明な場合は空文字列 "" を使用してください。
"""


def parse_json_response(response_text: str) -> dict:
    """Parse JSON from Gemini response."""
    try:
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()
        
        return json.loads(json_str)
    except (json.JSONDecodeError, IndexError) as e:
        st.error(f"JSON解析エラー: {e}")
        st.code(response_text, language="text")
        return None


def process_audio_only(audio_file_path: str) -> dict:
    """Process audio file and extract structured data."""
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=get_extraction_prompt()
    )
    
    uploaded_file = genai.upload_file(audio_file_path)
    prompt = "この音声ファイルの内容を聞き取り、営業報告データを抽出してください。"
    response = model.generate_content([uploaded_file, prompt])
    
    return parse_json_response(response.text)


def process_text_only(text: str) -> dict:
    """Process text input and extract structured data."""
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=get_extraction_prompt()
    )
    
    prompt = f"以下のテキストから営業報告データを抽出してください:\n\n{text}"
    response = model.generate_content(prompt)
    
    return parse_json_response(response.text)


def process_audio_and_text(audio_file_path: str, text: str) -> dict:
    """Process both audio and text, prioritizing text facts."""
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=get_extraction_prompt()
    )
    
    uploaded_file = genai.upload_file(audio_file_path)
    prompt = f"""
音声ファイルの内容を分析し、営業報告データを抽出してください。
ただし、以下のテキストメモに記載された事実を優先してください:

【テキストメモ（優先）】
{text}

音声とテキストの両方から情報を統合して、最も正確な営業報告データを作成してください。
"""
    response = model.generate_content([uploaded_file, prompt])
    
    return parse_json_response(response.text)


# =============================================================================
# AUDIO FILE HANDLING
# =============================================================================

def save_audio_file(uploaded_file) -> str:
    """Save uploaded audio file to local directory and return the path."""
    init_directories()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = Path(uploaded_file.name).stem
    extension = Path(uploaded_file.name).suffix
    filename = f"{timestamp}_{original_name}{extension}"
    
    file_path = SAVED_AUDIO_DIR / filename
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    
    return str(file_path)


# =============================================================================
# KINTONE INTEGRATION - 営業報告登録
# =============================================================================

def sanitize_text(text: str) -> str:
    """Remove control characters that break JSON."""
    if not text:
        return ""
    # Remove null bytes and other control characters
    import re
    # Keep only printable characters, newlines, tabs
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(text))
    return cleaned.strip()


def upload_file_to_kintone(file_path: str, file_name: str) -> str:
    """Upload a file to Kintone and return the file key."""
    if not all([KINTONE_SUBDOMAIN, KINTONE_API_TOKEN]):
        return ""
    
    url = f"https://{KINTONE_SUBDOMAIN}.cybozu.com/k/v1/file.json"
    headers = {
        "X-Cybozu-API-Token": KINTONE_API_TOKEN,
    }
    
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            response = requests.post(url, headers=headers, files=files)
            response.raise_for_status()
            return response.json().get("fileKey", "")
    except Exception as e:
        st.warning(f"ファイルアップロードエラー: {e}")
        return ""


def upload_to_kintone(data: dict, file_keys: list = None) -> bool:
    """Upload extracted data to Kintone."""
    if not all([KINTONE_SUBDOMAIN, KINTONE_APP_ID, KINTONE_API_TOKEN]):
        st.error("Kintone設定が不完全です。.envファイルを確認してください。")
        return False
    
    url = f"https://{KINTONE_SUBDOMAIN}.cybozu.com/k/v1/record.json"
    
    # ルックアップフィールドのため、両方のアプリのトークンを組み合わせる
    combined_token = KINTONE_API_TOKEN
    if KINTONE_CLIENT_API_TOKEN:
        combined_token = f"{KINTONE_API_TOKEN},{KINTONE_CLIENT_API_TOKEN}"
    
    headers = {
        "X-Cybozu-API-Token": combined_token,
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # Kintoneフィールドマッピング（テキストをサニタイズ）
    # 対応者はユーザー選択フィールドなので特別な形式で送信
    staff_name = data.get("対応者", "")
    staff_code = STAFF_CODE_MAP.get(staff_name, "")
    
    record = {
        "取引先ID": {"value": str(data.get("取引先ID", ""))},
        "新規営業件名": {"value": sanitize_text(data.get("新規営業件名", ""))},
        "対応日": {"value": sanitize_text(data.get("対応日", ""))},
        "対応者": {"value": [{"code": staff_code}] if staff_code else []},
        "商談内容": {"value": sanitize_text(data.get("商談内容", ""))},
        "現在の課題・問題点": {"value": sanitize_text(data.get("現在の課題・問題点", ""))},
        "競合・マーケット情報": {"value": sanitize_text(data.get("競合・マーケット情報", ""))},
        "次回提案内容": {"value": sanitize_text(data.get("次回提案内容", ""))},
        "次回提案予定日": {"value": sanitize_text(data.get("次回提案予定日", ""))},
        "次回営業件名": {"value": sanitize_text(data.get("次回営業件名", ""))},
    }
    
    # 添付ファイルを追加
    if file_keys:
        record["添付ファイル_0"] = {"value": [{"fileKey": fk} for fk in file_keys]}
    
    payload = {
        "app": int(KINTONE_APP_ID),
        "record": record
    }
    
    # デバッグ用：送信データ確認
    with st.expander("送信データ（デバッグ）"):
        st.json(payload)
    
    try:
        # json.dumps で明示的にエンコード（日本語を正しく処理）
        json_data = json.dumps(payload, ensure_ascii=False)
        response = requests.post(url, headers=headers, data=json_data.encode('utf-8'))
        response.raise_for_status()
        
        result = response.json()
        st.success(f"Kintoneにレコードを登録しました！ (ID: {result.get('id', 'N/A')})")
        return True
        
    except requests.exceptions.HTTPError as e:
        st.error(f"Kintone APIエラー: {e}")
        if response.text:
            st.code(response.text, language="json")
        return False
    except requests.exceptions.RequestException as e:
        st.error(f"通信エラー: {e}")
        return False


# =============================================================================
# STREAMLIT UI
# =============================================================================

def main():
    """Main application entry point."""
    
    st.set_page_config(
        page_title="営業報告アプリ",
        page_icon="icon.png",
        layout="centered"
    )
    
    st.title("📊 営業報告アプリ")
    st.markdown("音声またはテキストで営業活動を報告し、Kintoneに自動登録します。")
    
    st.divider()
    
    if not init_gemini():
        st.stop()
    
    # =========================================================================
    # SECTION 1: 基本情報入力
    # =========================================================================
    
    st.subheader("1. 基本情報")
    
    # 取引先検索
    col1, col2 = st.columns([3, 1])
    with col1:
        client_search = st.text_input("取引先名で検索", placeholder="会社名を入力...")
    with col2:
        search_button = st.button("検索", use_container_width=True)
    
    # 検索結果を保持
    if "client_results" not in st.session_state:
        st.session_state.client_results = []
    if "selected_client" not in st.session_state:
        st.session_state.selected_client = None
    
    if search_button and client_search:
        with st.spinner("検索中..."):
            st.session_state.client_results = search_clients(client_search)
    
    # 検索結果表示
    if st.session_state.client_results:
        client_options = {f"{c['name']} (ID: {c['id']})": c for c in st.session_state.client_results}
        selected = st.selectbox("取引先を選択", options=list(client_options.keys()))
        if selected:
            st.session_state.selected_client = client_options[selected]
            st.info(f"選択中: {st.session_state.selected_client['name']}")
    
    st.divider()
    
    # 営業件名
    sales_activity = st.selectbox("新規営業件名", options=SALES_ACTIVITY_OPTIONS)
    
    # 対応者（前回選択した人を記憶）
    # URLクエリパラメータで記憶
    query_params = st.query_params
    saved_staff = query_params.get("staff", STAFF_OPTIONS[0])
    if saved_staff not in STAFF_OPTIONS:
        saved_staff = STAFF_OPTIONS[0]
    
    default_staff_index = STAFF_OPTIONS.index(saved_staff) if saved_staff in STAFF_OPTIONS else 0
    staff = st.selectbox("対応者", options=STAFF_OPTIONS, index=default_staff_index)
    
    # 選択した対応者を記憶（URLに保存）
    if staff != saved_staff:
        st.query_params["staff"] = staff
    
    # 日付
    col1, col2 = st.columns(2)
    with col1:
        action_date = st.date_input("対応日", value=date.today())
    with col2:
        next_date = st.date_input("次回提案予定日", value=date.today())
    
    # 次回営業件名
    next_sales_activity = st.selectbox("次回営業件名", options=SALES_ACTIVITY_OPTIONS)
    
    st.divider()
    
    # =========================================================================
    # SECTION 1.5: 対応相手入力
    # =========================================================================
    
    st.subheader("1.5 対応相手（商談相手）")
    st.caption("商談内容の先頭に「○○部の△△様」として挿入されます")
    
    # 対応相手を管理
    if "contact_persons" not in st.session_state:
        st.session_state.contact_persons = [{"department": "", "name": ""}]
    
    # 対応相手の入力フィールド
    for i, contact in enumerate(st.session_state.contact_persons):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.session_state.contact_persons[i]["department"] = st.text_input(
                f"部署名 {i+1}" if i > 0 else "部署名",
                value=contact["department"],
                placeholder="例: 総務課",
                key=f"dept_{i}"
            )
        with col2:
            st.session_state.contact_persons[i]["name"] = st.text_input(
                f"お名前 {i+1}" if i > 0 else "お名前",
                value=contact["name"],
                placeholder="例: 有田",
                key=f"name_{i}"
            )
        with col3:
            if i > 0:
                if st.button("削除", key=f"del_{i}"):
                    st.session_state.contact_persons.pop(i)
                    st.rerun()
    
    # 追加ボタン
    if st.button("＋ 対応相手を追加"):
        st.session_state.contact_persons.append({"department": "", "name": ""})
        st.rerun()
    
    
    st.divider()
    
    # =========================================================================
    # SECTION 2: 音声/テキスト入力
    # =========================================================================
    
    st.subheader("2. 報告内容")
    
    # ファイルアップロード（音声またはテキストファイル）
    uploaded_file = st.file_uploader(
        "ファイルをアップロード（任意）",
        type=["mp3", "wav", "m4a", "webm", "txt"],
        help="対応形式: 音声(MP3, WAV, M4A, WebM) または テキスト(TXT)"
    )
    
    if uploaded_file:
        file_ext = uploaded_file.name.lower().split(".")[-1]
        if file_ext in ["mp3", "wav", "m4a", "webm"]:
            st.audio(uploaded_file)
        elif file_ext == "txt":
            st.success(f"テキストファイル: {uploaded_file.name}")
    
    # テキスト入力（直接入力）
    text_input = st.text_area(
        "テキストメモ（任意）",
        height=150,
        placeholder="商談内容、課題、競合情報などを入力..."
    )
    
    st.divider()
    
    # =========================================================================
    # SECTION 3: AI処理
    # =========================================================================
    
    st.subheader("3. AI処理")
    
    if st.button("🤖 AIで内容を抽出", type="primary", use_container_width=True):
        
        # バリデーション
        if not st.session_state.selected_client:
            st.warning("取引先を選択してください。")
            st.stop()
        
        if not uploaded_file and not text_input.strip():
            st.warning("ファイルまたはテキストを入力してください。")
            st.stop()
        
        with st.spinner("AIが内容を解析中..."):
            extracted_data = None
            saved_file_path = None
            is_audio = False
            file_content_for_ai = ""
            
            if uploaded_file:
                file_ext = uploaded_file.name.lower().split(".")[-1]
                
                if file_ext in ["mp3", "wav", "m4a", "webm"]:
                    # 音声ファイルの処理
                    is_audio = True
                    saved_file_path = save_audio_file(uploaded_file)
                elif file_ext == "txt":
                    # テキストファイルの処理 - 内容を読み込む
                    file_content_for_ai = uploaded_file.read().decode("utf-8")
                    # ファイルを保存（Kintone添付用）
                    init_directories()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    saved_file_path = str(SAVED_AUDIO_DIR / f"{timestamp}_{uploaded_file.name}")
                    with open(saved_file_path, "w", encoding="utf-8") as f:
                        f.write(file_content_for_ai)
            
            # AI処理実行
            if is_audio and saved_file_path:
                if text_input:
                    # 音声 + テキスト入力
                    extracted_data = process_audio_and_text(saved_file_path, text_input)
                else:
                    # 音声のみ
                    extracted_data = process_audio_only(saved_file_path)
            else:
                # テキストファイル or テキスト入力（両方あれば合成）
                combined_text = ""
                if file_content_for_ai:
                    combined_text += file_content_for_ai
                if text_input:
                    if combined_text:
                        combined_text += "\n\n--- 追加メモ ---\n" + text_input
                    else:
                        combined_text = text_input
                
                if combined_text:
                    extracted_data = process_text_only(combined_text)
            
            if extracted_data:
                # 対応相手を商談内容の先頭に追加
                contact_lines = []
                for contact in st.session_state.contact_persons:
                    dept = contact.get("department", "").strip()
                    name = contact.get("name", "").strip()
                    if dept and name:
                        contact_lines.append(f"{dept}の{name}様")
                    elif name:
                        contact_lines.append(f"{name}様")
                
                if contact_lines:
                    contact_header = "、".join(contact_lines)
                    original_content = extracted_data.get("商談内容", "")
                    extracted_data["商談内容"] = f"{contact_header}\n{original_content}"
                
                # 基本情報を追加
                extracted_data["取引先ID"] = st.session_state.selected_client["id"]
                extracted_data["新規営業件名"] = sales_activity
                extracted_data["対応者"] = staff
                extracted_data["対応日"] = action_date.strftime("%Y-%m-%d")
                extracted_data["次回提案予定日"] = next_date.strftime("%Y-%m-%d")
                extracted_data["次回営業件名"] = next_sales_activity
                
                # 添付ファイル用に保存
                st.session_state.uploaded_file_path = saved_file_path
                st.session_state.uploaded_file_name = uploaded_file.name if uploaded_file else None
                st.session_state.text_content = text_input if text_input else None
                
                st.session_state.extracted_data = extracted_data
                st.success("抽出完了！")
    
    # =========================================================================
    # SECTION 4: 抽出結果確認・編集
    # =========================================================================
    
    if "extracted_data" in st.session_state and st.session_state.extracted_data:
        st.divider()
        st.subheader("4. 抽出結果の確認・編集")
        
        data = st.session_state.extracted_data
        
        # 基本情報（読み取り専用）
        st.markdown("**基本情報**")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("取引先ID", value=data.get("取引先ID", ""), disabled=True)
            st.text_input("新規営業件名", value=data.get("新規営業件名", ""), disabled=True)
            st.text_input("対応日", value=data.get("対応日", ""), disabled=True)
        with col2:
            st.text_input("対応者", value=data.get("対応者", ""), disabled=True)
            st.text_input("次回提案予定日", value=data.get("次回提案予定日", ""), disabled=True)
            st.text_input("次回営業件名", value=data.get("次回営業件名", ""), disabled=True)
        
        st.markdown("**AI抽出内容（編集可能）**")
        
        # 編集可能フィールド
        data["商談内容"] = st.text_area(
            "商談内容",
            value=data.get("商談内容", ""),
            height=100
        )
        
        data["現在の課題・問題点"] = st.text_area(
            "現在の課題・問題点",
            value=data.get("現在の課題・問題点", ""),
            height=100
        )
        
        data["競合・マーケット情報"] = st.text_area(
            "競合・マーケット情報",
            value=data.get("競合・マーケット情報", ""),
            height=100
        )
        
        data["次回提案内容"] = st.text_area(
            "次回提案内容（より具体的に）",
            value=data.get("次回提案内容", ""),
            height=100
        )
        
        st.session_state.extracted_data = data
        
        st.divider()
        
        # =========================================================================
        # SECTION 5: Kintone登録
        # =========================================================================
        
        st.subheader("5. Kintoneへ登録")
        
        if st.button("📤 Kintoneに登録する", type="primary", use_container_width=True):
            with st.spinner("Kintoneに登録中..."):
                file_keys = []
                
                # アップロードしたファイルをKintoneに添付
                file_path = st.session_state.get("uploaded_file_path")
                file_name = st.session_state.get("uploaded_file_name")
                if file_path and file_name:
                    st.info(f"ファイルをアップロード中: {file_name}")
                    file_key = upload_file_to_kintone(file_path, file_name)
                    if file_key:
                        file_keys.append(file_key)
                
                # テキストメモをファイルとして保存・アップロード（ファイルがない場合のみ）
                text_content = st.session_state.get("text_content")
                if text_content and not file_path:
                    import tempfile
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    text_filename = f"memo_{timestamp}.txt"
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                        f.write(text_content)
                        text_path = f.name
                    st.info(f"テキストメモをアップロード中: {text_filename}")
                    file_key = upload_file_to_kintone(text_path, text_filename)
                    if file_key:
                        file_keys.append(file_key)
                
                # Kintoneにレコード登録
                if upload_to_kintone(st.session_state.extracted_data, file_keys if file_keys else None):
                    # 成功したらセッションをクリア
                    for key in ["extracted_data", "uploaded_file_path", "uploaded_file_name", "text_content"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.balloons()


if __name__ == "__main__":
    main()
