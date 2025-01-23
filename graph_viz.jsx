import React, { useEffect, useRef, useState } from 'react';
import { Camera } from 'lucide-react';

const GraphVisualization = () => {
  const svgRef = useRef(null);
  const [data, setData] = useState(window.graphData || { nodes: [], links: [] });
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  
  const width = 800;
  const height = 600;
  
  useEffect(() => {
    // Update data if window.graphData changes
    const handleDataUpdate = () => {
      if (window.graphData) {
        setData(window.graphData);
      }
    };
    
    window.addEventListener('graphDataUpdate', handleDataUpdate);
    return () => window.removeEventListener('graphDataUpdate', handleDataUpdate);
  }, []);

  const getNodeColor = (node) => {
    // Color nodes based on age
    const age = node.age || 0;
    if (age < 3600000) return '#60A5FA'; // Less than 1 hour old
    if (age < 86400000) return '#34D399'; // Less than 1 day old
    return '#A78BFA'; // Older than 1 day
  };

  return (
    <div className="w-full bg-gray-900 p-4 rounded-lg">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-white">Document Graph</h3>
        <button 
          className="p-2 bg-gray-800 rounded hover:bg-gray-700"
          onClick={() => {
            // Implement screenshot functionality
            const svg = svgRef.current;
            if (svg) {
              const svgData = new XMLSerializer().serializeToString(svg);
              const blob = new Blob([svgData], { type: 'image/svg+xml' });
              const url = URL.createObjectURL(blob);
              const link = document.createElement('a');
              link.href = url;
              link.download = 'graph.svg';
              link.click();
              URL.revokeObjectURL(url);
            }
          }}
        >
          <Camera className="w-5 h-5 text-gray-200" />
        </button>
      </div>
      
      <svg 
        ref={svgRef}
        width={width} 
        height={height} 
        className="bg-gray-800 rounded-lg"
        viewBox={`0 0 ${width} ${height}`}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {data.links.map((link, i) => (
            <line
              key={i}
              x1={data.nodes.find(n => n.id === link.source)?.x || 0}
              y1={data.nodes.find(n => n.id === link.source)?.y || 0}
              x2={data.nodes.find(n => n.id === link.target)?.x || 0}
              y2={data.nodes.find(n => n.id === link.target)?.y || 0}
              stroke="#374151"
              strokeWidth="1"
            />
          ))}
          
          {data.nodes.map((node, i) => (
            <g key={i} transform={`translate(${node.x || 0},${node.y || 0})`}>
              <circle
                r={8}
                fill={getNodeColor(node)}
                className="cursor-pointer hover:opacity-80"
              />
              <title>{node.label}</title>
            </g>
          ))}
        </g>
      </svg>

      <div className="mt-4 flex gap-4">
        <div className="flex items-center">
          <div className="w-3 h-3 rounded-full bg-blue-400 mr-2"></div>
          <span className="text-sm text-gray-300">New Documents (&lt;1h)</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded-full bg-green-400 mr-2"></div>
          <span className="text-sm text-gray-300">Recent (&lt;1d)</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded-full bg-purple-400 mr-2"></div>
          <span className="text-sm text-gray-300">Older Documents</span>
        </div>
      </div>
    </div>
  );
};

export default GraphVisualization;
