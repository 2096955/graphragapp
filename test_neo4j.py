from neo4j import GraphDatabase
import sys

def test_neo4j_connection():
    # Neo4j connection details
    uri = "neo4j+s://5a50d911.databases.neo4j.io"
    username = "neo4j"
    password = "izmc4aXhUOjjrm2-6HC3VT09HkadNA-nwAmZVqZzvAE"

    try:
        print("Testing Neo4j connection...")
        # Create driver
        driver = GraphDatabase.driver(uri, auth=(username, password))
        
        # Verify connection
        with driver.session() as session:
            # Simple test query
            result = session.run("MATCH (n) RETURN count(n) as node_count")
            count = result.single()["node_count"]
            print(f"Connection successful! Found {count} nodes in the database.")
            
            # Check for Document nodes specifically
            result = session.run("MATCH (n:Document) RETURN count(n) as doc_count")
            doc_count = result.single()["doc_count"]
            print(f"Found {doc_count} Document nodes.")
            
            # Check if vector index exists
            result = session.run("SHOW INDEXES")
            indexes = [record["name"] for record in result]
            print("\nAvailable indexes:", indexes)
            
            if "document-embeddings" in indexes:
                print("Vector index 'document-embeddings' exists!")
            else:
                print("Warning: Vector index 'document-embeddings' not found.")
        
        driver.close()
        print("\nAll Neo4j tests completed successfully!")
        
    except Exception as e:
        print(f"Error connecting to Neo4j: {str(e)}", file=sys.stderr)
        return False
    
    return True

if __name__ == "__main__":
    test_neo4j_connection()