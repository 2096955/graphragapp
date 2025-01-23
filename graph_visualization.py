import streamlit as st
import streamlit.components.v1 as components
import json
import logging
import time

logger = logging.getLogger(__name__)

class Neo4jManager:
    @staticmethod
    def clear_data(driver):
        try:
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            return True
        except Exception as e:
            logger.error(f"Error clearing data: {str(e)}")
            return False

def display_graph_visualization(driver):
    """Display graph visualization using Neo4j data"""
    try:
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🗑️ Clear All Data"):
                if Neo4jManager.clear_data(driver):
                    st.success("Successfully cleared data!")
                    time.sleep(1)
                    st.experimental_rerun()
                else:
                    st.error("Failed to clear data")

        with driver.session() as session:
            # Debug query results
            nodes_result = session.run("""
                MATCH (d:Document) 
                RETURN COUNT(d) as count
            """)
            count = nodes_result.single()["count"]
            st.write(f"Debug: Found {count} nodes")
            
            st.write("Debug: Attempting to load D3.js")
            
            # Get nodes with their properties
            nodes_result = session.run("""
                MATCH (d:Document)
                RETURN 
                    id(d) as id,
                    d.text as text,
                    datetime().epochMillis - d.timestamp.epochMillis as age
                LIMIT 100
            """)
            
            nodes = [{
                "id": str(record["id"]),
                "label": record["text"][:30] + "..." if record["text"] else "No text",
                "age": record["age"],
                "type": "document"
            } for record in nodes_result]
            
            rels_result = session.run("""
                MATCH (d1:Document)-[r]->(d2:Document)
                RETURN 
                    id(d1) as source,
                    id(d2) as target,
                    type(r) as type
                LIMIT 200
            """)
            
            links = [{
                "source": str(record["source"]),
                "target": str(record["target"]),
                "type": record["type"]
            } for record in rels_result]

            graph_data = {
                "nodes": nodes,
                "links": links
            }

            # Debug logging
            logger.info(f"Found {len(nodes)} nodes and {len(links)} links")
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <script src="https://d3js.org/d3.v7.min.js"></script>
                <style>
                    #graph-container {{
                        width: 100%;
                        height: 600px;
                        background: rgb(17, 24, 39);
                        border-radius: 0.5rem;
                    }}
                    .node {{
                        cursor: pointer;
                    }}
                    .node:hover circle {{
                        opacity: 0.8;
                    }}
                    .link {{
                        stroke: #374151;
                        stroke-width: 1px;
                    }}
                    .node-label {{
                        font-family: system-ui, -apple-system, sans-serif;
                        font-size: 12px;
                        fill: #E5E7EB;
                        pointer-events: none;
                    }}
                </style>
            </head>
            <body>
                <div id="graph-container"></div>
                <script>
                    const graphData = {json.dumps(graph_data)};
                    
                    const width = 800;
                    const height = 600;
                    
                    const svg = d3.select("#graph-container")
                        .append("svg")
                        .attr("width", "100%")
                        .attr("height", "100%")
                        .attr("viewBox", [0, 0, width, height])
                        .attr("style", "max-width: 100%; height: auto;");

                    const g = svg.append("g");
                    
                    const zoom = d3.zoom()
                        .scaleExtent([0.1, 4])
                        .on("zoom", (event) => g.attr("transform", event.transform));
                    
                    svg.call(zoom);
                    
                    const simulation = d3.forceSimulation(graphData.nodes)
                        .force("link", d3.forceLink(graphData.links)
                            .id(d => d.id)
                            .distance(100))
                        .force("charge", d3.forceManyBody().strength(-300))
                        .force("center", d3.forceCenter(width / 2, height / 2));

                    const link = g.append("g")
                        .selectAll("line")
                        .data(graphData.links)
                        .join("line")
                        .attr("class", "link");

                    const node = g.append("g")
                        .selectAll(".node")
                        .data(graphData.nodes)
                        .join("g")
                        .attr("class", "node")
                        .call(d3.drag()
                            .on("start", dragstarted)
                            .on("drag", dragged)
                            .on("end", dragended));

                    node.append("circle")
                        .attr("r", 8)
                        .attr("fill", d => {{
                            const age = d.age || 0;
                            if (age < 3600000) return '#60A5FA';
                            if (age < 86400000) return '#34D399';
                            return '#A78BFA';
                        }});

                    node.append("title")
                        .text(d => d.label);

                    node.append("text")
                        .attr("class", "node-label")
                        .attr("dx", 12)
                        .attr("dy", ".35em")
                        .text(d => d.label);

                    simulation.on("tick", () => {{
                        link
                            .attr("x1", d => d.source.x)
                            .attr("y1", d => d.source.y)
                            .attr("x2", d => d.target.x)
                            .attr("y2", d => d.target.y);

                        node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
                    }});

                    function dragstarted(event, d) {{
                        if (!event.active) simulation.alphaTarget(0.3).restart();
                        d.fx = d.x;
                        d.fy = d.y;
                    }}

                    function dragged(event, d) {{
                        d.fx = event.x;
                        d.fy = event.y;
                    }}

                    function dragended(event, d) {{
                        if (!event.active) simulation.alphaTarget(0);
                        d.fx = null;
                        d.fy = null;
                    }}

                    svg.call(zoom.transform, d3.zoomIdentity);
                </script>
            </body>
            </html>
            """
            
            components.html(html_content, height=700)

            # Display metrics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Documents", len(nodes))
            with col2:
                st.metric("Total Relationships", len(links))

    except Exception as e:
        logger.error(f"Error displaying visualization: {str(e)}")
        st.error("Failed to load graph visualization. Please try refreshing the page.")
