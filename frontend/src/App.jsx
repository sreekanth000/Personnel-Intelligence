import React, { useState, useEffect, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Brain, Database, Activity, RefreshCw, List, Share2 } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [stats, setStats] = useState({});
  const [insights, setInsights] = useState([]);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [activeView, setActiveView] = useState('graph');
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('Task');
  const [expandedNodeId, setExpandedNodeId] = useState(null);

  useEffect(() => {
    fetchData();
    const intervalId = setInterval(fetchData, 15000);
    
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight
        });
      }
    };
    
    window.addEventListener('resize', updateDimensions);
    // Initial delay to let CSS settle
    setTimeout(updateDimensions, 100);
    
    return () => {
      window.removeEventListener('resize', updateDimensions);
      clearInterval(intervalId);
    };
  }, []);

  const fetchData = async () => {
    try {
      const [graphRes, statsRes, insightsRes] = await Promise.all([
        fetch(`${API_BASE}/graph`),
        fetch(`${API_BASE}/stats`),
        fetch(`${API_BASE}/insights`)
      ]);
      
      const graph = await graphRes.json();
      const st = await statsRes.json();
      const ins = await insightsRes.json();
      
      // Filter out job posting tasks globally from UI
      const isJobPosting = (node) => {
        const textToSearch = [
           node.name,
           node.properties?.description,
           node.properties?.source,
           node.properties?.title,
           node.properties?.filepath
        ].filter(Boolean).join(' ').toLowerCase();
        
        return textToSearch.includes('jobposting') || textToSearch.includes('job posting');
      };
      
      graph.nodes = graph.nodes.filter(n => !isJobPosting(n));
      const validNodeIds = new Set(graph.nodes.map(n => n.id));
      graph.links = graph.links.filter(l => 
        validNodeIds.has(typeof l.source === 'object' ? l.source.id : l.source) && 
        validNodeIds.has(typeof l.target === 'object' ? l.target.id : l.target)
      );
      
      setGraphData(graph);
      setStats(st);
      setInsights(ins);
    } catch (err) {
      console.error("Error fetching data:", err);
    } finally {
      setLoading(false);
    }
  };

  const getNodeColor = (type) => {
    const colors = {
      Email: '#3b82f6', // Blue
      Person: '#10b981', // Green
      Task: '#f59e0b', // Orange
      Organization: '#8b5cf6', // Purple
      Event: '#ef4444', // Red
      Goal: '#ec4899', // Pink
    };
    return colors[type] || '#a1a1aa';
  };

  return (
    <div className="dashboard-container">
      {/* Sidebar Panel */}
      <div className="sidebar">
        <div className="sidebar-header">
          <h1><Brain size={24} color="#8b5cf6" /> Cognitive Brain</h1>
        </div>

        <div className="sidebar-section">
          <h2>World Model Stats</h2>
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-value" style={{color: getNodeColor('Email')}}>
                {stats.Email || 0}
              </div>
              <div className="stat-label">Base Emails</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{color: getNodeColor('Person')}}>
                {stats.Person || 0}
              </div>
              <div className="stat-label">People</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{color: getNodeColor('Organization')}}>
                {stats.Organization || 0}
              </div>
              <div className="stat-label">Organizations</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{color: getNodeColor('Task')}}>
                {stats.Task || 0}
              </div>
              <div className="stat-label">Inferred Tasks</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{color: '#ef4444'}}>
                {insights.length || 0}
              </div>
              <div className="stat-label">Active Insights</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{color: '#fff'}}>
                {stats.Relationships || 0}
              </div>
              <div className="stat-label">Neural Edges</div>
            </div>
          </div>
        </div>



        <div className="sidebar-section" style={{ marginTop: '32px' }}>
          <h2>Extracted Tasks</h2>
          <div className="task-list">
            {graphData.nodes.filter(n => n.group === 'Task').length > 0 ? (
              graphData.nodes.filter(n => n.group === 'Task').map((task) => (
                <div key={task.id} className="task-item" style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-start'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
                    <div className="task-indicator"></div>
                    <strong>{task.name}</strong>
                  </div>
                  {(task.properties?.start_time || task.properties?.deadline) && (
                    <div style={{fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', paddingLeft: '18px'}}>
                      {task.properties?.start_time && <span>Starts: {task.properties.start_time} </span>}
                      {task.properties?.deadline && <span>| Due: {task.properties.deadline}</span>}
                    </div>
                  )}
                  {task.properties?.description && (
                    <div style={{fontSize: '11px', color: 'rgba(255,255,255,0.6)', marginTop: '4px', paddingLeft: '18px', fontStyle: 'italic'}}>
                      {task.properties.description.substring(0, 60)}{task.properties.description.length > 60 ? '...' : ''}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div style={{color: 'var(--text-muted)', fontSize: '13px'}}>No tasks extracted yet.</div>
            )}
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <button 
          onClick={fetchData}
          style={{
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: '#fff',
            padding: '12px',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontWeight: 500,
            transition: 'all 0.2s'
          }}
          onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
          onMouseOut={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
        >
          <RefreshCw size={16} /> Sync Graph
        </button>
      </div>

      {/* Main Graph Area */}
      <div className="graph-container" ref={containerRef}>
        <div className="view-toggle">
          <button 
            className={`toggle-btn ${activeView === 'graph' ? 'active' : ''}`}
            onClick={() => setActiveView('graph')}
          >
            <Share2 size={16} /> Graph
          </button>
          <button 
            className={`toggle-btn ${activeView === 'tasks' ? 'active' : ''}`}
            onClick={() => setActiveView('tasks')}
          >
            <List size={16} /> Tasks
          </button>
          <button 
            className={`toggle-btn ${activeView === 'insights' ? 'active' : ''}`}
            onClick={() => setActiveView('insights')}
          >
            <Activity size={16} /> Insights
            {insights.length > 0 && (
              <span style={{background: '#ef4444', color: '#fff', fontSize: '10px', padding: '2px 6px', borderRadius: '10px', marginLeft: '6px', fontWeight: 'bold'}}>
                {insights.length}
              </span>
            )}
          </button>
        </div>

        {activeView === 'insights' && (
          <div className="insights-container">
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px'}}>
              <h2>AI Insights & Recommended Actions</h2>
            </div>
            
            {insights.length === 0 ? (
              <div style={{textAlign: 'center', color: 'var(--text-muted)', marginTop: '60px'}}>
                <Activity size={48} style={{opacity: 0.2, marginBottom: '16px'}} />
                <h3>All Clear</h3>
                <p>No active insights or recommendations at this time.</p>
              </div>
            ) : (
              <div className="insights-grid">
                {insights.map(insight => {
                  const sevColors = {
                    'Urgent': '#ef4444',
                    'High': '#f59e0b',
                    'Medium': '#3b82f6',
                    'Low': '#10b981'
                  };
                  const color = sevColors[insight.severity] || '#3b82f6';
                  
                  return (
                    <div key={insight.id} className="insight-card" style={{borderLeftColor: color}}>
                      <div className="insight-header">
                        <h3>{insight.name}</h3>
                        <span className="insight-badge" style={{background: `${color}33`, color: color, border: `1px solid ${color}55`}}>
                          {insight.severity}
                        </span>
                      </div>
                      <p className="insight-message">{insight.message}</p>
                      
                      <div className="insight-footer">
                        {insight.due_at && (
                          <span className="insight-due">
                            Due: {new Date(insight.due_at).toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}
                          </span>
                        )}
                        <button className="insight-action-btn" style={{background: `${color}15`, color: color, borderColor: `${color}55`}}>
                          Review Details
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeView === 'tasks' && (() => {
          const filteredNodes = graphData.nodes.filter(n => {
            if (filterType !== 'All' && n.group !== filterType) return false;
            if (searchQuery) {
              const query = searchQuery.toLowerCase();
              const nameMatch = n.name && n.name.toLowerCase().includes(query);
              const descMatch = n.properties?.description && n.properties.description.toLowerCase().includes(query);
              const sourceMatch = n.properties?.source && n.properties.source.toLowerCase().includes(query);
              if (!nameMatch && !descMatch && !sourceMatch) return false;
            }
            return true;
          });
          
          return (
            <div className="tasks-container">
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px'}}>
                <h2>Extracted Information Base</h2>
                <div style={{display: 'flex', gap: '12px'}}>
                  <input 
                    type="text" 
                    placeholder="Search details or source..." 
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    style={{padding: '8px 12px', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', border: '1px solid var(--border-color)', color: '#fff', outline: 'none', width: '250px'}}
                  />
                  <select 
                    value={filterType} 
                    onChange={e => setFilterType(e.target.value)}
                    style={{padding: '8px 12px', borderRadius: '6px', background: 'rgba(0,0,0,0.8)', border: '1px solid var(--border-color)', color: '#fff', outline: 'none', cursor: 'pointer'}}
                  >
                    <option value="Task">Tasks Only</option>
                    <option value="Person">People</option>
                    <option value="Organization">Organizations</option>
                    <option value="Event">Events / Meetings</option>
                    <option value="Document">Documents</option>
                    <option value="Email">Emails</option>
                    <option value="All">All Types</option>
                  </select>
                </div>
              </div>
              <div className="tasks-table-wrapper">
                <table className="tasks-table">
                  <thead>
                    <tr>
                      <th>Entity Type</th>
                      <th>Name / Title</th>
                      <th>Source Document</th>
                      <th>Timing / Metrics</th>
                      <th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredNodes.length > 0 ? (
                      filteredNodes.map(node => (
                        <React.Fragment key={node.id}>
                          <tr 
                            onClick={() => setExpandedNodeId(expandedNodeId === node.id ? null : node.id)}
                            style={{cursor: 'pointer', background: expandedNodeId === node.id ? 'rgba(255,255,255,0.05)' : 'transparent'}}
                            title="Click to view all metadata"
                          >
                            <td style={{verticalAlign: 'middle'}}>
                              <span style={{
                                background: 'rgba(255,255,255,0.1)', 
                                padding: '4px 8px', 
                                borderRadius: '12px', 
                                fontSize: '11px',
                                color: getNodeColor(node.group),
                                border: `1px solid ${getNodeColor(node.group)}40`
                              }}>
                                {node.group}
                              </span>
                            </td>
                            <td className="task-name-cell">
                              {node.name}
                            </td>
                            <td>{node.properties?.source || 'Extracted Node'}</td>
                            <td>
                              {node.properties?.start_time && <div><strong>Starts:</strong> {node.properties.start_time}</div>}
                              {node.properties?.deadline && <div><strong>Due:</strong> {node.properties.deadline}</div>}
                              {node.properties?.size && <div><strong>Size:</strong> {(node.properties.size / 1024).toFixed(2)} KB</div>}
                              {!node.properties?.start_time && !node.properties?.deadline && !node.properties?.size && <span style={{color: 'var(--text-muted)'}}>-</span>}
                            </td>
                            <td style={{maxWidth: '300px', whiteSpace: 'pre-wrap', fontStyle: 'italic'}}>
                              {node.properties?.description || node.properties?.content_preview?.substring(0, 100) + '...' || <span style={{color: 'var(--text-muted)'}}>No description available</span>}
                            </td>
                          </tr>
                          {expandedNodeId === node.id && (
                            <tr style={{background: 'rgba(0,0,0,0.3)'}}>
                              <td colSpan="5" style={{padding: '16px'}}>
                                <div style={{display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px'}}>
                                  <h4 style={{margin: '0 0 8px 0', color: '#fff'}}>All Metadata Details</h4>
                                  <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '12px'}}>
                                    {Object.entries(node.properties || {}).map(([k, v]) => (
                                      <div key={k} style={{background: 'rgba(255,255,255,0.05)', padding: '8px 12px', borderRadius: '6px'}}>
                                        <div style={{color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', marginBottom: '4px'}}>{k}</div>
                                        <div style={{color: '#fff', wordBreak: 'break-word'}}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</div>
                                      </div>
                                    ))}
                                    <div style={{background: 'rgba(255,255,255,0.05)', padding: '8px 12px', borderRadius: '6px'}}>
                                      <div style={{color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', marginBottom: '4px'}}>ID</div>
                                      <div style={{color: '#fff', wordBreak: 'break-all'}}>{node.id}</div>
                                    </div>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="5">
                          <div className="empty-state">No matching data found.</div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}

        {loading ? (
          <div className="loading-overlay">
            <div className="spinner"></div>
          </div>
        ) : (
          <ForceGraph2D
            width={dimensions.width}
            height={dimensions.height}
            graphData={graphData}
            nodeLabel="name"
            nodeColor={(node) => getNodeColor(node.group)}
            nodeRelSize={6}
            linkColor={() => 'rgba(255, 255, 255, 0.15)'}
            linkDirectionalParticles={2}
            linkDirectionalParticleSpeed={0.005}
            backgroundColor="transparent"
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
          />
        )}
      </div>
    </div>
  );
}

export default App;
