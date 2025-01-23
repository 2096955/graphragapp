import streamlit as st
from neo4j import GraphDatabase
from openai import AzureOpenAI
import os
import traceback

# Set up Azure OpenAI client
client = AzureOpenAI(
    api_key="3707d10eab2b4368b73998b8802838de",
    api_version="2024-08-01-preview",
    azure_endpoint="https://anthonylui.openai.azure.com"
)

def create_neo4j_connection():
    uri = "neo4j+s://5a50d911.databases.neo4j.io"
    username = "neo4j"
    password = "izmc4aXhUOjjrm2-6HC3VT09HkadNA-nwAmZVqZzvAE"
    
    driver = GraphDatabase.driver(uri, auth=(username, password))
    return driver

def query_neo4j(driver, query, params=None):
    with driver.session() as session:
        result = session.run(query, params or {})
        return [record for record in result]

def get_embedding(text):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-ada-002"  # Make sure this deployment exists in your Azure OpenAI
    )
    return response.data[0].embedding

def get_chat_completion(prompt):
    response = client.chat.completions.create(
        model="o1-preview-2",  # Your chat model deployment
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )
    return response.choices[0].message.content

def main():
    st.title("GraphRAG Question Answering System")
    
    # Create Neo4j connection
    driver = create_neo4j_connection()
    
    # Sidebar with settings
    st.sidebar.title("Settings")
    top_k = st.sidebar.number_input("Number of relevant documents", 1, 10, 3)
    temperature = st.sidebar.slider("Temperature", 0.0, 1.0, 0.0)
    
    # Main interface
    user_question = st.text_input("Ask your question:", "")
    
    if st.button("Get Answer"):
        if user_question:
            try:
                # Vector search query
                vector_search_query = """
                CALL db.index.vector.queryNodes('document-embeddings', \$top_k, \$embedding)
                YIELD node, score
                RETURN node.text AS text, score
                ORDER BY score DESC
                """
                
                # Get embedding for user question
                question_embedding = get_embedding(user_question)
                
                # Query Neo4j for relevant documents
                results = query_neo4j(
                    driver, 
                    vector_search_query, 
                    {"embedding": question_embedding, "top_k": top_k}
                )
                
                # Format context from results
                context = "\n".join([result["text"] for result in results])
                
                # Create prompt
                prompt = f"""
                Based on the following context, please answer the question: {user_question}
                
                Context:
                {context}
                
                Answer:
                """
                
                # Get response from Azure OpenAI
                response = get_chat_completion(prompt)
                
                # Display results
                st.write("### Answer:")
                st.write(response)
                
                with st.expander("View Related Documents"):
                    for idx, result in enumerate(results):
                        st.write(f"Document {idx + 1}:")
                        st.write(result["text"])
                        st.write("Score:", result["score"])
                        st.write("---")
                
                # Store in history
                if 'history' not in st.session_state:
                    st.session_state.history = []
                st.session_state.history.append((user_question, response))
                
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                st.error(f"Traceback: {traceback.format_exc()}")
    
    # Show history
    if st.sidebar.checkbox("Show History"):
        st.sidebar.title("Question History")
        if 'history' in st.session_state:
            for q, a in st.session_state.history:
                with st.sidebar.expander(q[:50] + "..."):
                    st.write("Q:", q)
                    st.write("A:", a)
    
    # Cleanup
    driver.close()

if __name__ == "__main__":
    main()
