"""
Sales Report App - Streamlit Application
Converts voice/text input into structured data using Gemini API and uploads to Kintone.
"""

import os
import json
import tempfile
from datetime import datetime
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
GEMINI_MODEL = "gemini-1.5-flash"

# Kintone API Configuration
KINTONE_SUBDOMAIN = os.getenv("KINTONE_SUBDOMAIN")
KINTONE_APP_ID = os.getenv("KINTONE_APP_ID")
KINTONE_API_TOKEN = os.getenv("KINTONE_API_TOKEN")

# Directory for saving audio files
SAVED_AUDIO_DIR = Path("./saved_audio")

# =============================================================================
# INITIALIZATION
# =============================================================================

def init_directories():
    """Create necessary directories if they don't exist."""
    SAVED_AUDIO_DIR.mkdir(exist_ok=True)


def init_gemini():
    """Initialize Gemini API client."""
    if not GEMINI_API_KEY:
        st.error("⚠️ GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")
        return False
    genai.configure(api_key=GEMINI_API_KEY)
    return True


# =============================================================================
# GEMINI AI PROCESSING
# =============================================================================

def get_extraction_prompt():
    """Return the system prompt for JSON extraction."""
    return """
あなたは営業報告データを抽出するAIアシスタントです。
入力された情報から以下のフィールドを抽出し、厳密なJSON形式で出力してください。

## 抽出フィールド:
- date: 活動日（YYYY-MM-DD形式）。明示されていない場合は今日の日付を使用。
- customer_name: 顧客名・会社名
- activity_detail: 活動内容の要約（簡潔に）
- next_action: 次に取るべきアクション

## 出力形式:
必ず以下のJSON形式のみを出力してください。説明や前置きは不要です。
```json
{
    "date": "YYYY-MM-DD",
    "customer_name": "顧客名",
    "activity_detail": "活動内容の要約",
    "next_action": "次のアクション"
}
```

情報が不明な場合は空文字列 "" を使用してください。
"""


def process_audio_only(audio_file_path: str) -> dict:
    """Process audio file and extract structured data."""
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=get_extraction_prompt()
    )
    
    # Upload audio file to Gemini
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
    
    # Upload audio file to Gemini
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


def parse_json_response(response_text: str) -> dict:
    """Parse JSON from Gemini response."""
    try:
        # Try to extract JSON from markdown code block
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


# =============================================================================
# AUDIO FILE HANDLING
# =============================================================================

def save_audio_file(uploaded_file) -> str:
    """Save uploaded audio file to local directory and return the path."""
    init_directories()
    
    # Generate unique filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = Path(uploaded_file.name).stem
    extension = Path(uploaded_file.name).suffix
    filename = f"{timestamp}_{original_name}{extension}"
    
    file_path = SAVED_AUDIO_DIR / filename
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    
    return str(file_path)


# =============================================================================
# KINTONE INTEGRATION
# =============================================================================

def upload_to_kintone(data: dict) -> bool:
    """
    Upload extracted data to Kintone.
    
    Kintone Field Mapping:
    ----------------------
    Change the field codes below to match your Kintone app's field settings.
    
    JSON Field      -> Kintone Field Code
    ----------------------------------------
    date            -> "日付"        (Date field)
    customer_name   -> "顧客名"      (Single-line text)
    activity_detail -> "活動内容"    (Multi-line text or Rich text)
    next_action     -> "次回アクション" (Multi-line text)
    
    To customize: Replace the Japanese field codes with your actual Kintone field codes.
    """
    
    if not all([KINTONE_SUBDOMAIN, KINTONE_APP_ID, KINTONE_API_TOKEN]):
        st.error("⚠️ Kintone設定が不完全です。.env ファイルを確認してください。")
        return False
    
    # Kintone API endpoint
    url = f"https://{KINTONE_SUBDOMAIN}.cybozu.com/k/v1/record.json"
    
    # Request headers
    headers = {
        "X-Cybozu-API-Token": KINTONE_API_TOKEN,
        "Content-Type": "application/json"
    }
    
    # ==========================================================================
    # KINTONE FIELD MAPPING
    # Modify the field codes (e.g., "日付", "顧客名") to match your Kintone app
    # ==========================================================================
    payload = {
        "app": KINTONE_APP_ID,
        "record": {
            # Field Code: "日付" - Date type field
            "日付": {
                "value": data.get("date", "")
            },
            # Field Code: "顧客名" - Single-line text field
            "顧客名": {
                "value": data.get("customer_name", "")
            },
            # Field Code: "活動内容" - Multi-line text field
            "活動内容": {
                "value": data.get("activity_detail", "")
            },
            # Field Code: "次回アクション" - Multi-line text field
            "次回アクション": {
                "value": data.get("next_action", "")
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        st.success(f"✅ Kintoneにレコードを登録しました！ (ID: {result.get('id', 'N/A')})")
        return True
        
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ Kintone APIエラー: {e}")
        if response.text:
            st.code(response.text, language="json")
        return False
    except requests.exceptions.RequestException as e:
        st.error(f"❌ 通信エラー: {e}")
        return False


# =============================================================================
# STREAMLIT UI
# =============================================================================

def main():
    """Main application entry point."""
    
    # Page configuration
    st.set_page_config(
        page_title="営業報告アプリ",
        page_icon="📊",
        layout="centered"
    )
    
    # Title and description
    st.title("📊 営業報告アプリ")
    st.markdown("音声またはテキストで営業活動を報告し、Kintoneに自動登録します。")
    
    st.divider()
    
    # Check Gemini API key
    if not init_gemini():
        st.stop()
    
    # ==========================================================================
    # INPUT SECTION
    # ==========================================================================
    
    st.subheader("📝 報告内容を入力")
    
    # Audio file uploader
    audio_file = st.file_uploader(
        "🎤 音声ファイルをアップロード（任意）",
        type=["mp3", "wav", "m4a"],
        help="対応形式: MP3, WAV, M4A"
    )
    
    # Text area for notes
    text_memo = st.text_area(
        "📋 メモ・備考（任意）",
        placeholder="例: 本日、ABC株式会社の田中様と商談。新製品の提案を行い、来週デモの約束を取り付けた。",
        height=150
    )
    
    st.divider()
    
    # ==========================================================================
    # SUBMIT BUTTON
    # ==========================================================================
    
    if st.button("🚀 送信・処理開始", type="primary", use_container_width=True):
        
        # Validate input
        if not audio_file and not text_memo.strip():
            st.warning("⚠️ 音声ファイルまたはテキストを入力してください。")
            st.stop()
        
        # Processing indicator
        with st.spinner("🔄 AIで処理中..."):
            
            extracted_data = None
            saved_audio_path = None
            
            try:
                # Determine processing pattern
                if audio_file and text_memo.strip():
                    # Pattern C: Audio + Text
                    st.info("🎯 音声＋テキストを分析中...")
                    saved_audio_path = save_audio_file(audio_file)
                    extracted_data = process_audio_and_text(saved_audio_path, text_memo)
                    
                elif audio_file:
                    # Pattern A: Audio only
                    st.info("🎯 音声を分析中...")
                    saved_audio_path = save_audio_file(audio_file)
                    extracted_data = process_audio_only(saved_audio_path)
                    
                else:
                    # Pattern B: Text only
                    st.info("🎯 テキストを分析中...")
                    extracted_data = process_text_only(text_memo)
                
            except Exception as e:
                st.error(f"❌ AI処理エラー: {e}")
                st.stop()
        
        # ==========================================================================
        # RESULTS DISPLAY
        # ==========================================================================
        
        if extracted_data:
            st.success("✅ データ抽出完了！")
            
            # Display extracted data
            st.subheader("📋 抽出結果")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("📅 日付", extracted_data.get("date", "N/A"))
                st.metric("🏢 顧客名", extracted_data.get("customer_name", "N/A"))
            with col2:
                st.text_area(
                    "📝 活動内容",
                    extracted_data.get("activity_detail", ""),
                    disabled=True,
                    height=80
                )
                st.text_area(
                    "➡️ 次回アクション",
                    extracted_data.get("next_action", ""),
                    disabled=True,
                    height=80
                )
            
            # Show raw JSON (expandable)
            with st.expander("🔍 JSON データを確認"):
                st.json(extracted_data)
            
            if saved_audio_path:
                st.info(f"📁 音声ファイル保存先: `{saved_audio_path}`")
            
            st.divider()
            
            # ==========================================================================
            # KINTONE UPLOAD
            # ==========================================================================
            
            st.subheader("📤 Kintoneへ登録")
            
            if st.button("⬆️ Kintoneに登録する", type="secondary", use_container_width=True):
                with st.spinner("Kintoneに登録中..."):
                    upload_to_kintone(extracted_data)
        else:
            st.error("❌ データの抽出に失敗しました。入力内容を確認してください。")
    
    # ==========================================================================
    # FOOTER
    # ==========================================================================
    
    st.divider()
    st.caption("💡 Powered by Google Gemini AI & Kintone")


if __name__ == "__main__":
    main()
