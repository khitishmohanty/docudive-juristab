import json

class HtmlGenerator:
    """
    Generates an interactive HTML tree visualization from a JurisMap JSON object.
    """

    def generate_html_tree(self, json_data: dict) -> str:
        """
        Takes a dictionary parsed from the JurisMap JSON and returns a complete
        HTML string for the interactive tree visualization with updated styles and animations.

        Args:
            json_data (dict): The case data parsed from a JSON file.

        Returns:
            str: A self-contained HTML document as a string.
        """
        json_string_for_html = json.dumps(json_data)

        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JurisMap Visualization</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Poppins', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            overflow: hidden;
        }}
        .chart-container {{
            display: flex;
            flex-direction: row;
            align-items: flex-start;
            gap: 40px;
            width: 100%;
            max-width: 1800px;
            margin: auto;
        }}
        .tree-container {{
            flex-grow: 1;
            position: relative;
        }}
        .sidebar {{
            width: 300px;
            flex-shrink: 0;
        }}
        .details-panel, .legend-panel {{
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
        }}
        .details-panel h3, .legend-panel h3 {{
            margin-top: 0;
            color: black;
            font-weight: normal;
            border-bottom: 1px solid #dee2e6;
            padding-bottom: 10px;
        }}
        .details-panel p {{
            color: #7A7171;
            font-size: 14px;
            line-height: 1.5;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 10px;
            font-size: 12px;
            color: #7A7171;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 4px;
            margin-right: 10px;
        }}
        .node {{
             cursor: pointer;
        }}
        .node rect {{
            stroke: none;
            transition: transform 0.2s ease-in-out;
        }}
        .node:hover rect {{
            transform: scale(1.05);
        }}
        .node text {{
            font-size: 8px;
            text-anchor: middle;
            fill: #333;
            pointer-events: none;
        }}
        .node .type-label {{
            font-size: 11px;
            font-weight: 500;
            fill: white;
            text-anchor: middle;
            pointer-events: none;
        }}
        .link-group .link {{
            fill: none;
            stroke: #ccc;
            stroke-width: 1.5px;
        }}
        .link-group .link-hitbox {{
            fill: none;
            stroke: transparent;
            stroke-width: 15px;
            cursor: pointer;
        }}
        .link-group:hover .link {{
            stroke: #343a40;
        }}
        .level-label {{
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
            fill: #7A7171;
        }}
        .level-line {{
            stroke: #adb5bd;
            stroke-dasharray: 4, 4;
        }}
        #arrowhead path {{
            fill: #ccc;
        }}
        .link-group:hover #arrowhead path {{
            fill: #343a40;
        }}
    </style>
</head>
<body>
    <div class="chart-container">
        <div class="tree-container">
            <svg id="tree-svg"></svg>
        </div>
        <div class="sidebar">
            <div class="details-panel" id="details-panel">
                <h3>Details</h3>
                <p id="details-text">Select a person or relationship on the map to see more details here.</p>
            </div>
            <div class="legend-panel" id="legend-panel">
                <h3>Legends</h3>
            </div>
        </div>
    </div>

    <script>
        const data = {json_string_for_html};
        const defaultDetailsText = "Select a person or relationship on the map to see more details here.";

        const colorMap = {{
            'Judiciary': '#6f42c1', 'Prosecution': '#fd7e14', 'Plaintiff': '#fd7e14',
            'Defendant': '#0d6efd', 'Accused': '#0d6efd', 'Victim': '#20c997',
            'Co-offender': '#dc3545', 'Third Party': '#ffc107', 'Insurer': '#6610f2',
            'Intervener': '#17a2b8', 'Legal Representative': '#0dcaf0', 'Legal Firm': '#0dcaf0',
            'Other parties': '#6c757d'
        }};
        
        // FIX: Create a dynamic legend based on types present in the data
        const presentTypes = new Set(data.levels.flatMap(l => l.parties.map(p => p.type)));
        
        const legendData = Object.entries(colorMap).reduce((acc, [type, color]) => {{
            if (presentTypes.has(type)) {{
                if (!acc[color]) {{
                    acc[color] = [];
                }}
                acc[color].push(type);
            }}
            return acc;
        }}, {{}});

        const legendPanel = document.getElementById('legend-panel');
        Object.entries(legendData).forEach(([color, types]) => {{
            const item = document.createElement('div');
            item.className = 'legend-item';
            const label = types.join(' / ');
            item.innerHTML = `<div class="legend-color" style="background-color: ${{color}};"></div><span>${{label}}</span>`;
            legendPanel.appendChild(item);
        }});

        const width = document.querySelector('.tree-container').clientWidth;
        const svg = d3.select("#tree-svg").attr("width", width);
        
        const defs = svg.append('defs');
        defs.append('marker')
            .attr('id', 'arrowhead')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 5).attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 6).attr('markerHeight', 6)
            .append('svg:path')
            .attr('d', 'M 0,-5 L 10 ,0 L 0,5')
            .attr('fill', '#ccc');

        defs.append('marker')
            .attr('id', 'arrowhead-hover')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 5).attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 6).attr('markerHeight', 6)
            .append('svg:path')
            .attr('d', 'M 0,-5 L 10 ,0 L 0,5')
            .attr('fill', '#343a40');


        const g = svg.append("g");
        const zoom = d3.zoom().on("zoom", (event) => g.attr("transform", event.transform));
        svg.call(zoom);

        const nodes = [];
        const nodeMap = new Map();
        const levelInfo = new Map();
        const nodeWidth = 70;
        const nodeHeight = 28;
        const nodesPerRow = Math.floor(width / (nodeWidth + 25));

        let yPos = 120;

        data.levels.forEach(level => {{
            const numNodes = level.parties.length;
            const numRows = Math.ceil(numNodes / nodesPerRow);
            const levelHeight = Math.max(120, numRows * (nodeHeight + 50));

            levelInfo.set(level.level_number, {{ y: yPos, height: levelHeight }});
            
            level.parties.forEach(party => {{
                nodes.push({{ 
                    id: party.name, ...party, 
                    level: level.level_number
                }});
                nodeMap.set(party.name, nodes[nodes.length - 1]);
            }});
            yPos += levelHeight;
        }});
        
        svg.attr("height", yPos);

        const links = data.connections.map(d => ({{ 
            source: nodeMap.get(d.source), 
            target: nodeMap.get(d.target),
            relationship: d.relationship 
        }})).filter(l => l.source && l.target);

        levelInfo.forEach((info, levelNumber) => {{
            const levelData = data.levels.find(l => l.level_number === levelNumber);
            g.append("text").attr("x", 50).attr("y", info.y - 40).attr("class", "level-label").text(levelData.level_description);
            g.append("line").attr("x1", 50).attr("x2", width - 50).attr("y1", info.y - 30).attr("y2", info.y - 30).attr("class", "level-line");
        }});

        const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(100).strength(0.6))
            .force("charge", d3.forceManyBody().strength(-150))
            .force("collide", d3.forceCollide().radius(nodeWidth / 2 + 10).strength(1))
            .force("x", d3.forceX(width / 2).strength(0.05));

        const linkGroup = g.append("g").selectAll("g").data(links).join("g")
            .attr("class", "link-group")
            .on("mouseover", function(event, d) {{
                const currentLink = d3.select(this);
                currentLink.raise();
                currentLink.select('.link').attr('marker-end', 'url(#arrowhead-hover)');
                const relationshipHTML = `
                    <span>${{d.source.id}}</span>
                    <strong style="color: black;">${{d.relationship}}</strong>
                    <span>${{d.target.id}}</span>
                `;
                document.getElementById('details-text').innerHTML = relationshipHTML;
            }})
            .on("mouseout", function() {{
                const currentLink = d3.select(this);
                currentLink.select('.link').attr('marker-end', 'url(#arrowhead)');
                document.getElementById('details-text').innerHTML = defaultDetailsText;
            }});

        const node = g.append("g").selectAll("g").data(nodes).join("g")
            .attr("class", "node")
            .call(drag(simulation));
            
        const getPath = d => {{
            const startPoint = getIntersectionPoint(d.target, d.source, nodeWidth, nodeHeight);
            const endPoint = getIntersectionPoint(d.source, d.target, nodeWidth, nodeHeight);
            return `M${{startPoint.x}},${{startPoint.y}} C ${{startPoint.x}},${{(startPoint.y + endPoint.y) / 2}} ${{endPoint.x}},${{(startPoint.y + endPoint.y) / 2}} ${{endPoint.x}},${{endPoint.y}}`;
        }};
        
        linkGroup.append("path").attr("class", "link-hitbox").attr("d", getPath);
        const visibleLink = linkGroup.append("path").attr("class", "link").attr('marker-end','url(#arrowhead)').attr("d", getPath);
        
        node.append("rect")
            .attr("x", -nodeWidth / 2).attr("y", -nodeHeight / 2)
            .attr("width", nodeWidth).attr("height", nodeHeight)
            .attr("rx", 15).attr("ry", 15)
            .attr("fill", d => colorMap[d.type] || colorMap['Other parties']);
        
        node.append("text").attr("class", "type-label").attr("dy", "0.3em").text(d => d.type.substring(0, 1));
        const nameLabel = node.append("text").attr("y", nodeHeight / 2 + 3).attr("dy", "0.5em").text(d => d.name);

        node.style("opacity", 0).transition().duration(700).delay((d, i) => i * 15).style("opacity", 1);
        linkGroup.style("opacity", 0).transition().duration(700).delay(200).style("opacity", 1);

        simulation.on("tick", () => {{
            nodes.forEach(d => {{
                const levelData = levelInfo.get(d.level);
                const padding = 20;
                const upper_bound = levelData.y - 30 + (nodeHeight / 2) + padding;
                const lower_bound = levelData.y + levelData.height - 40 - (nodeHeight / 2) - padding;
                d.y = Math.max(upper_bound, Math.min(lower_bound, d.y));
            }});
        
            visibleLink.attr("d", getPath);
            linkGroup.selectAll(".link-hitbox").attr("d", getPath);
            node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
            nameLabel.call(wrap, nodeWidth - 5);
        }});
        
        function getIntersectionPoint(source, target, width, height) {{
            const dx = target.x - source.x;
            const dy = target.y - source.y;
            const w = width / 2;
            const h = height / 2;
            const angle = Math.atan2(dy, dx);
            const rectAngle = Math.atan2(h, w);
            
            let x, y;
            if (angle > -rectAngle && angle < rectAngle) {{
                x = target.x - w; y = target.y - w * Math.tan(angle);
            }} else if (angle > rectAngle && angle < Math.PI - rectAngle) {{
                x = target.x - h / Math.tan(angle); y = target.y - h;
            }} else if (angle < -rectAngle && angle > -Math.PI + rectAngle) {{
                x = target.x + h / Math.tan(angle); y = target.y + h;
            }} else {{
                x = target.x + w; y = target.y + w * Math.tan(angle);
            }}
            return {{x, y}};
        }}

        function drag(simulation) {{
            let dragstarted_x, dragstarted_y;

            function dragstarted(event, d) {{
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = event.x; d.fy = event.y;
                dragstarted_x = event.x;
                dragstarted_y = event.y;
                d3.select(this).raise();
            }}
            function dragged(event, d) {{
                d.fx = event.x; d.fy = event.y;
            }}
            function dragended(event, d) {{
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null; d.fy = null;
                
                const dist = Math.sqrt(Math.pow(event.x - dragstarted_x, 2) + Math.pow(event.y - dragstarted_y, 2));
                if (dist < 3) {{
                    document.getElementById('details-text').textContent = d.description;
                }}
            }}
            return d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended);
        }}

        function wrap(text, width) {{
            text.each(function() {{
                var text = d3.select(this), words = text.text().split(/\\s+/).reverse(), word, line = [],
                    lineNumber = 0, lineHeight = 1.1, y = text.attr("y"), dy = parseFloat(text.attr("dy")),
                    tspan = text.text(null).append("tspan").attr("x", 0).attr("y", y).attr("dy", dy + "em");
                while (word = words.pop()) {{
                    line.push(word);
                    tspan.text(line.join(" "));
                    if (tspan.node().getComputedTextLength() > width) {{
                        line.pop();
                        tspan.text(line.join(" "));
                        line = [word];
                        tspan = text.append("tspan").attr("x", 0).attr("y", y).attr("dy", ++lineNumber * lineHeight + dy + "em").text(word);
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>
        """
        return html_template
