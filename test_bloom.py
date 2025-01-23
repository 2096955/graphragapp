import streamlit as st
import streamlit.components.v1 as components
from neo4j import GraphDatabase
import pandas as pd
import traceback
from urllib.parse import urlparse
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_neo4j_driver():
    """Create Neo4j driver with error handling and connection testing"""
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
        st.error("Failed to connect to database. Please check your credentials.")
        return None

def get_bloom_url():
    """Get Bloom URL without exposing database ID"""
    try:
        base_uri = st.secrets["NEO4J_URI"]
        parsed = urlparse(base_uri)
        # Return generic Bloom URL
        return "https://bloom.neo4j.io"
    except Exception as e:
        logger.error(f"Error generating Bloom URL: {str(e)}")
        return None

def upload_file_to_neo4j(driver, file):
    if not driver:
        return
    
    try:
        df = pd.read_csv(file)
        
        # Show only row count, not data preview
        st.info(f"Processing {len(df)} records...")
        
        with driver.session() as session:
            if st.checkbox("Clear existing data before upload"):
                session.run("MATCH (n) DETACH DELETE n")
            
            # Batch process records
            batch_size = 100
            for i in range(0, len(df), batch_size):
                batch = df[i:i+batch_size]
                
                # Use parameterized queries for safety
                for _, record in batch.iterrows():
                    text = record['text']
                    cypher_query = """
                    CREATE (d:Incident {
                        id: $id,
                        text: $text,
                        type: CASE 
                            WHEN $text CONTAINS 'System' THEN 'System'
                            WHEN $text CONTAINS 'Account' THEN 'Account'
                            ELSE 'Other'
                        END
                    })
                    """
                    session.run(cypher_query, 
                              id=f"incident_{i}",
                              text=text)
                
                # Show progress
                progress = min((i + batch_size) / len(df), 1.0)
                st.progress(progress)

        st.success("Data uploaded successfully!")
        
        # Provide generic visualization instructions
        st.markdown("""
        ### View in Neo4j Bloom
        
        1. Open Neo4j Bloom
        2. Use this Cypher query:
        ```
        MATCH (i:Incident)
        RETURN i
        ```
        3. Customize visualization as needed
        """)
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        st.error("Error uploading data. Please check the file format and try again.")

def main():
    st.title("Incident Data Uploader")
    
    driver = create_neo4j_driver()
    if not driver:
        return
        
    try:
        st.header("Upload Data")
        uploaded_file = st.file_uploader("Upload CSV file", type="csv")
        if uploaded_file:
            upload_file_to_neo4j(driver, uploaded_file)
            
        # Show minimal database status
        with driver.session() as session:
            count = session.run("MATCH (n:Incident) RETURN count(n) as count").single()["count"]
            st.metric("Total Incidents", count)
            
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        st.error("An error occurred. Please try again or contact support.")
    finally:
        if driver:
            driver.close()

if __name__ == "__main__":
    main()