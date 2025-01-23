import streamlit as st
from neo4j import GraphDatabase
from openai import AzureOpenAI
import pandas as pd
import traceback
import logging
import numpy as np
import time
import traceback
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
    def get_embeddings_batch(texts, batch_size=20):
        embeddings = AzureOpenAIEmbeddings(
            deployment=st.secrets["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
            azure_endpoint=st.secrets["AZURE_OPENAI_ENDPOINT"].rstrip('/'),
            api_key=st.secrets["AZURE_OPENAI_API_KEY"],
            api_version="2024-05-01-preview"
        )
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend(embeddings.embed_documents(batch))
        return results

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

    # Update Neo4jVector initialization
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
                text_node_properties=["text"],
            #    retrieval_query="""
            #    CALL db.index.vector.queryNodes($index_name, $k, $vector) 
            #    YIELD node, similarityScore 
            #    WHERE node.text IS NOT NULL 
            #    RETURN node.text AS text, node.embedding AS embedding, similarityScore as score
            #    """
            )
            return vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 5})
        except Exception as e:
            logger.error(f"Vector store initialization error: {str(e)}")
            raise

    # Update visualization queries
    def get_nodes():
        return """
        MATCH (d:Document)
        RETURN 
            elementId(d) as id,
            d.text as text,
            datetime().epochMillis - d.timestamp.epochMillis as age
        LIMIT 100
        """

    def get_relationships():
        return """
        MATCH (d1:Document)-[r]->(d2:Document)
        RETURN 
            elementId(d1) as source,
            elementId(d2) as target,
            type(r) as type
        LIMIT 200
        """

    def create_similarity_relationships(session, similarities):
        for rel in similarities:
            session.run("""
            MATCH (d1:Document)
            WHERE elementId(d1) = $id1
            MATCH (d2:Document) 
            WHERE elementId(d2) = $id2
            MERGE (d1)-[r:SIMILAR_TO]->(d2)
            ON CREATE SET r.similarity = $sim
            ON MATCH SET r.similarity = $sim
            """, id1=rel['id1'], id2=rel['id2'], sim=rel['sim'])

    # Update deprecated Neo4j queries
    @staticmethod
    def upload_file(driver, file):
        start = time.time()
        df = pd.read_csv(file)
        texts = df['text'].tolist()
        
        logger.info(f"Starting embeddings batch: {time.time() - start:.2f}s")
        embeddings = AzureOpenAIClient.get_embeddings_batch(texts)
        logger.info(f"Embeddings complete: {time.time() - start:.2f}s")
    
        with driver.session() as session:
            # Update duplicate removal query
            session.run("""
            MATCH (n:Document)
            WITH n.text as text, collect(n) as duplicates, count(*) as count
            WHERE count > 1
            WITH duplicates[0] as keep, duplicates[1..] as removals
            WITH removals
            UNWIND removals as removal
            DETACH DELETE removal
            RETURN count(keep)
            """)
            
            # Update node creation
            result = session.run("""
            UNWIND $nodes AS node
            MERGE (n:Document {text: node.text})
            ON CREATE SET n.embedding = node.embedding,
                        n.timestamp = datetime()
            ON MATCH SET n.embedding = node.embedding,
                        n.timestamp = datetime()
            RETURN collect(elementId(n)) as ids
            """, nodes=[{'text': t, 'embedding': e} for t, e in zip(texts, embeddings)])

            # Update similarity relationships
            if similarities:
                session.run("""
                UNWIND $rels AS rel
                MATCH (d1:Document)
                MATCH (d2:Document)
                WHERE elementId(d1) = rel.id1 AND elementId(d2) = rel.id2
                MERGE (d1)-[r:SIMILAR_TO]->(d2)
                ON CREATE SET r.similarity = rel.sim
                ON MATCH SET r.similarity = rel.sim
                """, rels=similarities)

    @staticmethod
    def upload_file(driver, file):
        start = time.time()
        df = pd.read_csv(file)
        texts = df['text'].tolist()
        
        logger.info(f"Starting embeddings batch: {time.time() - start:.2f}s")
        embeddings = AzureOpenAIClient.get_embeddings_batch(texts)
        logger.info(f"Embeddings complete: {time.time() - start:.2f}s")
        
        with driver.session() as session:
            # First, remove duplicates in existing data
            session.run("""
            MATCH (n:Document)
            WITH n.text as text, collect(n) as duplicates, count(*) as count
            WHERE count > 1
            WITH duplicates[0] as keep, duplicates[1..] as removals
            CALL {
                WITH removals
                UNWIND removals as removal
                DETACH DELETE removal
            }
            RETURN count(keep)
            """)
            
            # Then proceed with merge operation
            result = session.run("""
            UNWIND $nodes AS node
            MERGE (n:Document {text: node.text})
            ON CREATE SET n.embedding = node.embedding,
                        n.timestamp = datetime()
            ON MATCH SET n.embedding = node.embedding,
                        n.timestamp = datetime()
            RETURN collect(elementId(n)) as ids
            """, nodes=[{'text': t, 'embedding': e} for t, e in zip(texts, embeddings)])
            
            node_ids = result.single()["ids"]
            
            # Update similarities
            similarities = []
            for i, (id1, emb1) in enumerate(zip(node_ids, embeddings)):
                for j, (id2, emb2) in enumerate(zip(node_ids[i+1:], embeddings[i+1:]), i+1):
                    sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
                    if sim > 0.8:
                        similarities.append({'id1': id1, 'id2': id2, 'sim': float(sim)})
            
            if similarities:
                session.run("""
                UNWIND $rels AS rel
                MATCH (d1:Document), (d2:Document)
                WHERE elementId(d1) = rel.id1 AND elementId(d2) = rel.id2
                MERGE (d1)-[r:SIMILAR_TO]->(d2)
                ON CREATE SET r.similarity = rel.sim
                ON MATCH SET r.similarity = rel.sim
                """, rels=similarities)
        
        return True
             
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
            logger.info("Starting query processing...")
            context_docs = self.retriever.invoke(user_input)
            logger.info(f"Retrieved {len(context_docs)} documents")
            
            if not context_docs:
                logger.warning("No documents retrieved")
                return "No relevant documents found to answer your question."
                
            context = "\n\n".join([doc.page_content for doc in context_docs])
            logger.info(f"Built context of length: {len(context)}")
            
            messages = [{"role": "user", "content": f"Context: {context}\nQuestion: {user_input}\nAnswer:"}]
            response = self.client.chat.completions.create(
                model=st.secrets["AZURE_OPENAI_DEPLOYMENT_NAME"],
                messages=messages,
                temperature=1
            )
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Query processing error: {str(e)}\n{traceback.format_exc()}")
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
