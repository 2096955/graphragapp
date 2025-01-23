from openai import AzureOpenAI
import streamlit as st

def test_azure_connection():
    # Initialize the client
    client = AzureOpenAI(
        azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"],
        api_key=st.secrets["AZURE_OPENAI_API_KEY"],
        api_version="2024-05-01-preview"
    )
    
    try:
        # Test chat completion
        print("Testing chat completion...")
        response = client.chat.completions.create(
            model=st.secrets["AZURE_OPENAI_DEPLOYMENT_NAME"],
            messages=[{"role": "user", "content": "Say 'Hello, this is a test'"}]
        )
        print("Chat response:", response.choices[0].message.content)
        print("Chat test successful!")
        
    except Exception as e:
        print("Chat test failed:", str(e))

if __name__ == "__main__":
    test_azure_connection()
