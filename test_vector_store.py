from neo4j import GraphDatabase
from openai import AzureOpenAI
import json

def test_vector_storage():
    # Azure OpenAI setup
    client = AzureOpenAI(
        azure_endpoint="https://anthonylui.openai.azure.com",
        api_key="3707d10eab2b4368b73998b8802838de",
        api_version="2024-05-01-preview"
    )

    # Neo4j setup
    uri = st.secrets["NEO4J_URI"]
    username = st.secrets["NEO4J_USERNAME"]
    password = st.secrets["NEO4J_PASSWORD"]
    driver = GraphDatabase.driver(uri, auth=(username, password))

    try:
        print("Starting vector store test...")

        # 1. Generate an embedding for test data
        test_text = "This is a test document about artificial intelligence and machine learning."
        print("\nGenerating embedding...")
        response = client.embeddings.create(
            model="text-embedding-ada-002",
            input=test_text
        )
        embedding = response.data[0].embedding
        print(f"Generated embedding of length: {len(embedding)}")

        # 2. Store in Neo4j
        print("\nStoring in Neo4j...")
        with driver.session() as session:
            # First, clean up any previous test nodes
            session.run("MATCH (n:TestDocument) DETACH DELETE n")
            
            # Create new test node with embedding
            result = session.run("""
                CREATE (d:TestDocument {
                    text: $text,
                    embedding: $embedding
                })
                RETURN d
                """,
                text=test_text,
                embedding=embedding
            )
            print("Test document stored successfully")

            # 3. Verify vector index
            print("\nChecking indexes...")
            indexes = session.run("SHOW INDEXES").data()
            print("Available indexes:")
            for idx in indexes:
                print(f"- {idx['name']}: {idx['type']}")

            # 4. Try a vector similarity search using native vector search
            print("\nTesting similarity search...")
            search_query = """
            CALL db.index.vector.queryNodes($index_name, $top_k, $query_vector) 
            YIELD node, score
            RETURN node.text AS text, score
            """
            
            search_result = session.run(
                search_query,
                index_name="form_10k_chunks",
                top_k=5,
                query_vector=embedding
            ).data()

            if search_result:
                print("\nSearch results:")
                for record in search_result:
                    print(f"Text: {record['text']}")
                    print(f"Similarity score: {record['score']}")
            else:
                print("\nNo results found in vector search")

        print("\nVector store test completed successfully!")

    except Exception as e:
        print(f"Error during test: {str(e)}")
        print("\nTrying to diagnose the issue...")
        with driver.session() as session:
            # Check if the index is properly configured
            index_info = session.run("""
                SHOW INDEXES
                WHERE name = 'form_10k_chunks'
                RETURN *
            """).data()
            print("\nIndex details:")
            print(json.dumps(index_info, indent=2))

    finally:
        driver.close()

if __name__ == "__main__":
    test_vector_storage()  # Changed from test_vector_store to test_vector_storage
