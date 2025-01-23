import streamlit as st
from neo4j import GraphDatabase
from openai import AzureOpenAI
import pandas as pd
import traceback
import logging
import numpy as np
from graph_visualization import display_graph_visualization

# LangChain imports
from langchain_core.prompts import PromptTemplate
from langchain_openai import AzureOpenAIEmbeddings, ChatOpenAI
from langchain_neo4j import Neo4jVector

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AzureOpenAIClient:
    @staticmethod
    def init_client():
        return AzureOpenAI(
            azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"].rstrip('/'),
            api_key=st.secrets["AZURE_OPENAI_API_KEY"],
            api_version="2024-05-01-preview"
        )

    @staticmethod
    def get_embedding(text):
        try:
            embeddings = AzureOpenAIEmbeddings(
                deployment=st.secrets["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
                azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"].rstrip('/'),
                api_key=st.secrets["AZURE_OPENAI_API_KEY"],
                api_version="2024-05-01-preview"
            )
            return embeddings.embed_query(text)
        except Exception as e:
            logger.error(f"Embedding Error: {str(e)}")
            raise

class Neo4jManager:
    @staticmethod
    def create_driver():
        try:
            uri = st.secrets["NEO4J_URI"]
            username = st.secrets["NEO4J_USERNAME"]
            password = st.secrets["NEO4J_PASSWORD"]
            driver = GraphDatabase.driver(uri, auth=(username, password))
            # Test connection
            with driver.session() as session:
                session.run("RETURN 1")
            return driver
        except Exception as e:
            logger.error(f"Failed to create Neo4j driver: {str(e)}")
            raise

    @staticmethod
    def init_vector_store():
        try:
            embedding_model = AzureOpenAIEmbeddings(
                deployment=st.secrets["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
                azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"].rstrip('/'),
                api_key=st.secrets["AZURE_OPENAI_API_KEY"],
                api_version="2024-05-01-preview"
            )

            vector_store = Neo4jVector.from_existing_graph(
                embedding=embedding_model,
                url=st.secrets["NEO4J_URI"],
                username=st.secrets["NEO4J_USERNAME"],
                password=st.secrets["NEO4J_PASSWORD"],
                index_name="form_10k_chunks",
                node_label="Document",
                embedding_node_property="embedding",
                text_node_properties=["text"]
            )
            
            return vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 5})
        except Exception as e:
            logger.error(f"Error initializing vector store: {str(e)}")
            raise

    @staticmethod
    def upload_file(driver, file):
        try:
            df = pd.read_csv(file)
            total_records = len(df)
            progress_bar = st.progress(0)
            
            with driver.session() as session:
                # First create all nodes
                node_ids = []  # Store node IDs for creating relationships
                for index, record in df.iterrows():
                    embedding = AzureOpenAIClient.get_embedding(record['text'])
                    
                    # Create node and get its ID
                    result = session.run("""
                    CREATE (n:Document {
                        text: $text,
                        embedding: $embedding,
                        timestamp: datetime()
                    })
                    RETURN id(n) as node_id
                    """, text=record['text'], embedding=embedding)
                    
                    node_ids.append(result.single()["node_id"])
                    
                    # Update progress
                    progress = (index + 1) / (total_records * 2)  # Divide by 2 since we have two phases
                    progress_bar.progress(progress)
                
                # Now create relationships between similar documents
                for i, id1 in enumerate(node_ids):
                    # Get the embedding for this document
                    result = session.run("""
                    MATCH (d:Document)
                    WHERE id(d) = $id
                    RETURN d.embedding as embedding
                    """, id=id1)
                    embedding1 = result.single()["embedding"]
                    
                    # Find similar documents and create relationships
                    for j, id2 in enumerate(node_ids[i+1:], i+1):
                        result = session.run("""
                        MATCH (d:Document)
                        WHERE id(d) = $id
                        RETURN d.embedding as embedding
                        """, id=id2)
                        embedding2 = result.single()["embedding"]
                        
                        # Calculate cosine similarity
                        similarity = np.dot(embedding1, embedding2) / (
                            np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
                        )
                        
                        # If documents are similar enough, create a relationship
                        if similarity > 0.8:  # Threshold for similarity
                            session.run("""
                            MATCH (d1:Document), (d2:Document)
                            WHERE id(d1) = $id1 AND id(d2) = $id2
                            CREATE (d1)-[:SIMILAR_TO {similarity: $similarity}]->(d2)
                            """, id1=id1, id2=id2, similarity=float(similarity))
                    
                    # Update progress for second phase
                    progress = 0.5 + ((i + 1) / total_records * 0.5)
                    progress_bar.progress(progress)
                
            st.success(f"Successfully uploaded {total_records} records and created relationships!")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            st.error(f"Upload failed: {str(e)}")
            return False
        
    @staticmethod
    def clear_data(driver):
        try:
            with driver.session() as session:
                session.run("MATCH (n:Document) DETACH DELETE n")
            return True
        except Exception as e:
            logger.error(f"Error clearing data: {str(e)}")
            return False

class ChatInterface:
    def __init__(self, retriever, client):
        self.retriever = retriever
        self.client = client

    def process_query(self, user_input):
        try:
            # Get context from retriever
            context_docs = self.retriever.invoke(user_input)
            context = "\n\n".join([doc.page_content for doc in context_docs])
            
            # Format messages
            messages = [{
                "role": "user", 
                "content": f"""You are a helpful assistant that answers questions based on the provided context.
                Please answer the following question based on this context:
                
                Context: {context}
                Question: {user_input}
                Answer: """
            }]

            # Get completion
            with st.spinner('Processing your question...'):
                response = self.client.chat.completions.create(
                    model=st.secrets["AZURE_OPENAI_DEPLOYMENT_NAME"],
                    messages=messages,
                    temperature=1
                )
                return response.choices[0].message.content
                
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            raise

def main():
    st.title("Graph RAG with Neo4j and Azure OpenAI")
    
    try:
        # Initialize services
        driver = Neo4jManager.create_driver()
        
        # Create tabs
        tab1, tab2, tab3 = st.tabs(["Upload", "Visualization", "Chat"])
        
        with tab1:
            st.header("Upload Data")
            uploaded_file = st.file_uploader("Upload a CSV file with 'text' column", type="csv")
            if uploaded_file:
                Neo4jManager.upload_file(driver, uploaded_file)
        
        with tab2:
            st.header("Graph Visualization")
            try:
                if driver:
                    # Test connection
                    with driver.session() as session:
                        result = session.run("MATCH (n:Document) RETURN count(n) as count")
                        count = result.single()["count"]
                        st.info(f"Found {count} documents in the database")
                        
                    if count > 0:
                        display_graph_visualization(driver)
                    else:
                        st.warning("No documents found. Please upload some data first.")
            except Exception as e:
                st.error(f"Visualization error: {str(e)}")
                logger.error(f"Visualization error: {traceback.format_exc()}")
        
        with tab3:
            st.header("Chat with your data")
            
            # Initialize chat components
            retriever = Neo4jManager.init_vector_store()
            client = AzureOpenAIClient.init_client()
            chat_interface = ChatInterface(retriever, client)
            
            # Chat input
            user_input = st.text_input("Ask a question:")
            if user_input:
                try:
                    result = chat_interface.process_query(user_input)
                    st.markdown(f"**Answer:** {result}")
                except Exception as e:
                    st.error("Failed to process your question. Please try again.")

    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        st.error("An error occurred. Please check the logs or contact support.")

if __name__ == "__main__":
    main()
