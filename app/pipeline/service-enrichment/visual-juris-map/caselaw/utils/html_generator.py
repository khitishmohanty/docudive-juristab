import json

class HtmlGenerator:
    """
    Generates an interactive HTML page with two switchable visualizations
    (Force-Directed Graph and Chord Diagram) from a JurisMap JSON object.
    """

    def generate_html_tree(self, json_data: dict) -> str:
        """
        Takes a dictionary parsed from the JurisMap JSON and returns a complete
        HTML string for an interactive page with two chart types.

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
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Poppins', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #fff;
        }}
        .view-toggle {{
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 20px;
        }}
        .toggle-switch {{
            position: relative;
            display: inline-block;
            width: 60px;
            height: 34px;
        }}
        .toggle-switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 34px;
        }}
        .slider:before {{
            position: absolute;
            content: "";
            height: 26px;
            width: 26px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }}
        input:checked + .slider {{
            background-color: #888;
        }}
        input:checked + .slider:before {{
            transform: translateX(26px);
        }}
        .toggle-label {{
            margin: 0 10px;
            font-weight: 500;
            font-size: 14px;
            color: #333;
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
        .tree-container, .chord-container {{
            flex-grow: 1;
            position: relative;
            min-height: 600px;
            opacity: 0;
            transform: translateY(15px);
            transition: opacity 0.5s ease-in-out, transform 0.5s ease-in-out;
        }}
        .is-visible {{
            opacity: 1;
            transform: translateY(0);
        }}
        #chord-container {{
            display: none;
        }}
        #tree-svg, #chord-svg {{
            width: 100%;
            height: 100%;
            display: block;
        }}
        .sidebar {{
            width: 300px;
            flex-shrink: 0;
        }}
        .details-panel {{
            background-color: white;
            border-radius: 8px;
            border: 1px solid #e9ecef;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .details-panel h3 {{
            margin-top: 0; color: black; font-weight: 500;
            border-bottom: 1px solid #dee2e6; padding-bottom: 10px; font-size: 16px;
        }}
        .details-panel p {{
            color: #7A7171; font-size: 12px; line-height: 1.5;
            transition: opacity 0.2s ease-in-out;
        }}
        .node {{ cursor: pointer; }}
        .node rect {{ stroke: none; transition: transform 0.2s ease-in-out; }}
        .node:hover rect {{ transform: scale(1.05); }}
        .node text {{ font-size: 8px; text-anchor: middle; fill: #333; pointer-events: none; }}
        .node .type-label {{ font-size: 11px; font-weight: 500; fill: white; pointer-events: none; }}
        .link-group .link {{ fill: none; stroke: #ccc; stroke-width: 1.5px; }}
        .link-group:hover .link {{ stroke: #343a40; }}
        #arrowhead path {{ fill: #ccc; }}
        .link-group:hover #arrowhead path {{ fill: #343a40; }}

        /* Chord Diagram Styles */
        .chord-group, .chord-path, .chord-label-group {{
            transition: opacity 0.2s ease-in-out;
        }}
        .chord-group.faded, .chord-path.faded, .chord-label-group.faded {{
            opacity: 0.1;
        }}
        .chord-group {{ cursor: pointer; }}
        .chord-group path {{
            fill-opacity: 0.8;
            transition: fill-opacity 0.2s ease-in-out;
        }}
        .chord-path {{ 
            fill-opacity: 0.65;
            stroke: #fff; 
            stroke-width: 0.5px; 
        }}
        
        .chord-label-group {{
            cursor: pointer;
        }}
        .chord-label-group .leader-line {{
            fill: none;
            stroke: #aaa;
            stroke-width: 1px;
        }}
        .chord-label-group text {{
            font-size: 12px;
            font-weight: 400;
            fill: #333;
            stroke: #333;
            stroke-width: 0;
            transition: stroke-width 0.2s ease-in-out;
        }}
        .chord-label-group .party-type {{
            fill: #6c757d;
            stroke: #6c757d;
        }}
        .chord-label-group .underline {{
            stroke-width: 2.5px;
        }}
        .chord-label-group:hover text,
        .chord-label-group.selected text {{
            stroke-width: 0.4px;
        }}
    </style>
</head>
<body>
    <div class="chart-container">
        <div class="tree-container" id="tree-container">
            <svg id="tree-svg"></svg>
        </div>
        <div class="chord-container" id="chord-container">
            <svg id="chord-svg"></svg>
        </div>
        <div class="sidebar">
            <div class="view-toggle">
                <span class="toggle-label">Force Graph</span>
                <label class="toggle-switch">
                    <input type="checkbox" id="view-toggle-checkbox">
                    <span class="slider"></span>
                </label>
                <span class="toggle-label">Chord Diagram</span>
            </div>
            <div class="details-panel" id="details-panel">
                <h3>Details</h3>
                <p id="details-text">Select a person or relationship on the map to see more details here.</p>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            const data = {json_string_for_html};
            const defaultDetailsText = "Select a person or relationship on the map to see more details here.";

            const colorMap = {{
                'Judiciary': '#6f42c1', 'Prosecution': '#fd7e14', 'Plaintiff': '#fd7e14',
                'Defendant': '#0d6efd', 'Accused': '#0d6efd', 'Victim': '#20c997',
                'Co-offender': '#dc3545', 'Third Party': '#ffc107', 'Insurer': '#6610f2',
                'Intervener': '#17a2b8', 'Legal Representative': '#0dcaf0', 'Legal Firm': '#0dcaf0',
                'Other parties': '#6c757d'
            }};

            const treeContainer = document.getElementById('tree-container');
            const chordContainer = document.getElementById('chord-container');
            const toggle = document.getElementById('view-toggle-checkbox');
            let isTreeRendered = false;
            let isChordRendered = false;

            toggle.addEventListener('change', function() {{
                const showChord = this.checked;
                setTimeout(() => {{
                    if (showChord) {{
                        treeContainer.style.display = 'none';
                        chordContainer.style.display = 'flex';
                        if (!isChordRendered) {{
                            renderChordChart();
                            isChordRendered = true;
                        }}
                        requestAnimationFrame(() => chordContainer.classList.add('is-visible'));
                    }} else {{
                        treeContainer.style.display = 'none';
                        treeContainer.style.display = 'block';
                        requestAnimationFrame(() => treeContainer.classList.add('is-visible'));
                    }}
                }}, 500);

                if (showChord) {{
                    treeContainer.classList.remove('is-visible');
                }} else {{
                    chordContainer.classList.remove('is-visible');
                }}
            }});

            renderChart();
            isTreeRendered = true;
            treeContainer.style.display = 'block';
            requestAnimationFrame(() => {{
                treeContainer.classList.add('is-visible');
            }});

            function renderChordChart() {{
                const svg = d3.select("#chord-svg");
                svg.selectAll("*").remove();
                const containerWidth = document.querySelector('.chord-container').clientWidth;
                const containerHeight = document.querySelector('.chord-container').clientHeight;
                const outerRadius = Math.min(containerWidth, containerHeight) * 0.5 - 160;
                const innerRadius = outerRadius - 20;
                svg.attr("width", containerWidth).attr("height", containerHeight);
                const g = svg.append("g").attr("transform", "translate(" + containerWidth / 2 + "," + containerHeight / 2 + ")");
                
                svg.on("click", () => {{
                    g.selectAll(".chord-label-group.selected").dispatch("mouseout");
                    g.selectAll(".chord-label-group").classed("selected", false);
                    unhighlightAll();
                    updateDetails(defaultDetailsText);
                }});

                const parties = data.levels.flatMap(l => l.parties);
                const nameToIndex = new Map(parties.map((p, i) => [p.name, i]));
                const indexToParty = new Map(parties.map((p, i) => [i, p]));
                const matrix = Array.from({{length: parties.length}}, () => Array(parties.length).fill(0));
                data.connections.forEach(conn => {{
                    const sourceIndex = nameToIndex.get(conn.source);
                    const targetIndex = nameToIndex.get(conn.target);
                    if (sourceIndex !== undefined && targetIndex !== undefined) matrix[sourceIndex][targetIndex] += 1;
                }});
                const chord = d3.chordDirected().padAngle(0.05).sortSubgroups(d3.descending).sortChords(d3.descending);
                const chords = chord(matrix);

                function highlightConnections(d) {{
                    const partyIndex = d.index;
                    const connectedIndices = new Set([partyIndex]);
                    g.selectAll(".chord-path")
                        .filter(c => c.source.index === partyIndex || c.target.index === partyIndex)
                        .each(c => {{
                            connectedIndices.add(c.source.index);
                            connectedIndices.add(c.target.index);
                        }});
                    
                    g.selectAll(".chord-group").classed("faded", gd => !connectedIndices.has(gd.index));
                    g.selectAll(".chord-path").classed("faded", c => !(c.source.index === partyIndex || c.target.index === partyIndex));
                    g.selectAll(".chord-label-group").classed("faded", ld => !connectedIndices.has(ld.index));
                    
                    g.selectAll(".chord-path:not(.faded)").style("fill-opacity", 0.9);
                    g.selectAll(".chord-group:not(.faded) path").style("fill-opacity", 1.0);
                }}

                function unhighlightAll() {{
                    g.selectAll(".faded").classed("faded", false);
                    g.selectAll(".chord-path").style("fill-opacity", 0.65);
                    g.selectAll(".chord-group path").style("fill-opacity", 0.8);
                }}
                
                const group = g.append("g").selectAll("g").data(chords.groups).join("g").attr("class", "chord-group")
                    .on("mouseover", (event, d) => highlightConnections(d))
                    .on("mouseout", function() {{
                        if (!g.select(".chord-label-group.selected").node()) {{
                            unhighlightAll();
                        }}
                    }})
                    .on("click", (event, d) => {{
                        event.stopPropagation();
                        const labelNode = g.selectAll(".chord-label-group").filter(ld => ld.index === d.index).node();
                        if (labelNode) {{
                            d3.select(labelNode).dispatch("click");
                        }}
                    }});

                group.append("path")
                    .attr("fill", d => colorMap[indexToParty.get(d.index).type] || '#ccc')
                    .attr("stroke", d => d3.rgb(colorMap[indexToParty.get(d.index).type] || '#ccc').darker())
                    .attr("d", d3.arc()({{innerRadius: innerRadius, outerRadius: outerRadius}}));
                
                g.append("g").selectAll("path").data(chords).join("path")
                    .attr("class", "chord-path")
                    .attr("d", d3.ribbonArrow().radius(innerRadius - 1))
                    .attr("fill", d => colorMap[indexToParty.get(d.source.index).type] || '#ccc')
                    .attr("stroke", d => d3.rgb(colorMap[indexToParty.get(d.source.index).type] || '#ccc').darker());
                
                const labelData = chords.groups.map(d => {{
                    const party = indexToParty.get(d.index);
                    const midAngle = (d.startAngle + d.endAngle) / 2;
                    return {{
                        angle: midAngle,
                        name: party.name,
                        type: party.type,
                        color: colorMap[party.type] || '#ccc',
                        description: party.description,
                        index: d.index
                    }};
                }});

                const labelHeight = 16;
                const rightLabels = labelData.filter(l => l.angle < Math.PI).sort((a,b) => a.angle - b.angle);
                const leftLabels = labelData.filter(l => l.angle >= Math.PI).sort((a,b) => b.angle - a.angle);
                
                let lastYRight = -Infinity;
                rightLabels.forEach(label => {{
                    const angle = label.angle - Math.PI / 2;
                    let y = (outerRadius + 30) * Math.sin(angle);
                    if (y < lastYRight + labelHeight) y = lastYRight + labelHeight;
                    lastYRight = y;
                    label.finalY = y;
                }});
                
                let lastYLeft = -Infinity;
                leftLabels.forEach(label => {{
                    const angle = label.angle - Math.PI / 2;
                    let y = (outerRadius + 30) * Math.sin(angle);
                    if (y < lastYLeft + labelHeight) y = lastYLeft + labelHeight;
                    lastYLeft = y;
                    label.finalY = y;
                }});

                const labelGroup = g.append("g").selectAll("g").data(labelData).join("g")
                    .attr("class", "chord-label-group")
                    .on("mouseover", function(event, d) {{
                        highlightConnections(d);
                        const underline = d3.select(this).select(".underline");
                        const x1 = parseFloat(underline.attr("data-og-x1"));
                        const x2 = parseFloat(underline.attr("data-og-x2"));
                        const onRightSide = d.angle < Math.PI;
                        underline.transition().duration(200)
                            .attr(onRightSide ? "x2" : "x1", onRightSide ? x2 + 5 : x1 - 5);
                    }})
                    .on("mouseout", function() {{
                        if (d3.select(this).classed("selected")) return;
                        unhighlightAll();
                        const underline = d3.select(this).select(".underline");
                        underline.transition().duration(200)
                            .attr("x1", underline.attr("data-og-x1"))
                            .attr("x2", underline.attr("data-og-x2"));
                    }})
                    .on("click", function(event, d) {{
                        event.stopPropagation();
                        const group = d3.select(this);
                        const isAlreadySelected = group.classed("selected");

                        g.selectAll(".chord-label-group.selected").each(function() {{
                            d3.select(this).classed("selected", false).dispatch("mouseout");
                        }});
                        
                        group.classed("selected", !isAlreadySelected);
                        
                        if (!isAlreadySelected) {{
                            updateDetails(d.description);
                            group.dispatch("mouseover");
                        }} else {{
                            updateDetails(defaultDetailsText);
                            group.dispatch("mouseout");
                        }}
                    }});

                labelGroup.append("path")
                    .attr("class", "leader-line")
                    .attr("d", d => {{
                        const angle = d.angle - Math.PI / 2;
                        const onRightSide = d.angle < Math.PI;
                        const startX = (outerRadius + 2) * Math.cos(angle);
                        const startY = (outerRadius + 2) * Math.sin(angle);
                        const elbowX = (outerRadius + 40) * (onRightSide ? 1 : -1);
                        return "M" + startX + "," + startY + "C" + elbowX + "," + startY + " " + elbowX + "," + d.finalY + " " + elbowX + "," + d.finalY;
                    }});

                const textLabels = labelGroup.append("text")
                    .attr("transform", d => {{
                        const onRightSide = d.angle < Math.PI;
                        const x = (outerRadius + 45) * (onRightSide ? 1 : -1);
                        return "translate(" + x + "," + d.finalY + ")";
                    }})
                    .attr("dy", "0.35em")
                    .attr("text-anchor", d => d.angle < Math.PI ? "start" : "end");
                
                textLabels.append("tspan").text(d => d.name);
                textLabels.append("tspan").attr("class", "party-type").attr("dx", " 5").text(d => " (" + d.type + ")");
                
                labelGroup.each(function(d) {{
                    const group = d3.select(this);
                    const textNode = group.select("text").node();
                    if (!textNode) return;
                    
                    const bbox = textNode.getBBox();
                    group.append("line")
                        .attr("class", "underline")
                        .attr("stroke", d.color)
                        .attr("transform", group.select("text").attr("transform"))
                        .attr("x1", bbox.x)
                        .attr("x2", bbox.x + bbox.width)
                        .attr("y1", bbox.y + bbox.height + 1)
                        .attr("y2", bbox.y + bbox.height + 1)
                        .attr("data-og-x1", bbox.x)
                        .attr("data-og-x2", bbox.x + bbox.width);
                }});
            }}

            function renderChart() {{
                const svg = d3.select("#tree-svg");
                svg.selectAll("*").remove();
                const width = document.querySelector('.tree-container').clientWidth;
                if (width <= 0) {{ setTimeout(renderChart, 100); return; }}
                svg.attr("width", width);
                const defs = svg.append('defs');

                defs.append('marker').attr('id', 'arrowhead').attr('viewBox', '-0 -5 10 10')
                    .attr('refX', 10).attr('refY', 0).attr('orient', 'auto')
                    .attr('markerWidth', 6).attr('markerHeight', 6)
                    .append('svg:path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#ccc');
                defs.append('marker').attr('id', 'arrowhead-hover').attr('viewBox', '-0 -5 10 10')
                    .attr('refX', 10).attr('refY', 0).attr('orient', 'auto')
                    .attr('markerWidth', 6).attr('markerHeight', 6)
                    .append('svg:path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#343a40');

                const g = svg.append("g");
                const zoom = d3.zoom().on("zoom", (event) => g.attr("transform", event.transform));
                svg.call(zoom);
                const nodes = [];
                const nodeMap = new Map();
                const levelInfo = new Map();
                const nodeWidth = 70, nodeHeight = 28;
                const nodesPerRow = Math.floor(width / (nodeWidth + 25));
                let yPos = 1;
                data.levels.forEach(level => {{
                    const numRows = Math.ceil(level.parties.length / nodesPerRow);
                    const levelHeight = Math.max(120, numRows * (nodeHeight + 50));
                    levelInfo.set(level.level_number, {{ y: yPos, height: levelHeight }});
                    level.parties.forEach(party => {{
                        nodes.push({{ id: party.name, ...party, level: level.level_number }});
                        nodeMap.set(party.name, nodes[nodes.length - 1]);
                    }});
                    yPos += levelHeight;
                }});
                svg.attr("height", yPos);
                const links = data.connections.map(d => ({{ source: nodeMap.get(d.source), target: nodeMap.get(d.target), relationship: d.relationship }})).filter(l => l.source && l.target);
                nodes.forEach(node => {{
                    const levelData = levelInfo.get(node.level);
                    if (levelData) node.y = levelData.y + levelData.height / 2;
                }});
                levelInfo.forEach((info, levelNumber) => {{
                    const levelData = data.levels.find(l => l.level_number === levelNumber);
                    g.append("line").attr("x1", 50).attr("x2", width - 50).attr("y1", info.y).attr("y2", info.y).attr("class", "level-line");
                    g.append("text").attr("x", 50).attr("y", info.y + 15).attr("class", "level-label").text(levelData.level_description);
                }});
                const simulation = d3.forceSimulation(nodes)
                    .force("link", d3.forceLink(links).id(d => d.id).distance(100).strength(0.6))
                    .force("charge", d3.forceManyBody().strength(-150))
                    .force("collide", d3.forceCollide().radius(nodeWidth / 2 + 10).strength(1))
                    .force("x", d3.forceX(width / 2).strength(0.05));
                const linkGroup = g.append("g").selectAll("g").data(links).join("g").attr("class", "link-group")
                    .on("mouseover", function(event, d) {{
                        d3.select(this).raise().select('.link').attr('marker-end', 'url(#arrowhead-hover)');
                        updateDetails('<span>' + d.source.id + '</span> <strong style="color: black;">' + d.relationship + '</strong> <span>' + d.target.id + '</span>');
                    }})
                    .on("mouseout", function() {{
                        d3.select(this).select('.link').attr('marker-end', 'url(#arrowhead)');
                        updateDetails(defaultDetailsText);
                    }});
                const node = g.append("g").selectAll("g").data(nodes).join("g").attr("class", "node").call(drag(simulation));
                
                const getPath = d => {{
                    if (!d.source || !d.target) return "";
                    const startPoint = getIntersectionPoint(d.target, d.source, nodeWidth, nodeHeight);
                    const endPoint = getIntersectionPoint(d.source, d.target, nodeWidth, nodeHeight);
                    return "M" + startPoint.x + "," + startPoint.y + " C " + startPoint.x + "," + (startPoint.y + endPoint.y) / 2 + " " + endPoint.x + "," + (startPoint.y + endPoint.y) / 2 + " " + endPoint.x + "," + endPoint.y;
                }};

                linkGroup.append("path").attr("class", "link-hitbox").attr("d", getPath);
                const visibleLink = linkGroup.append("path").attr("class", "link").attr('marker-end','url(#arrowhead)').attr("d", getPath);
                
                node.append("rect").attr("x", -nodeWidth / 2).attr("y", -nodeHeight / 2).attr("width", nodeWidth).attr("height", nodeHeight).attr("rx", 15).attr("ry", 15).attr("fill", d => colorMap[d.type] || colorMap['Other parties']);
                node.append("text").attr("class", "type-label").attr("dy", "0.3em").text(d => d.type.substring(0, 1));
                const nameLabel = node.append("text").attr("y", nodeHeight / 2 + 3).attr("dy", "0.5em").text(d => d.name);

                simulation.on("tick", () => {{
                    nodes.forEach(d => {{
                        const levelData = levelInfo.get(d.level);
                        const padding = 35;
                        d.y = Math.max(levelData.y + (nodeHeight / 2) + padding, Math.min(levelData.y + levelData.height - (nodeHeight / 2) - padding, d.y));
                    }});
                    visibleLink.attr("d", getPath);
                    linkGroup.selectAll(".link-hitbox").attr("d", getPath);
                    node.attr("transform", d => "translate(" + d.x + "," + d.y + ")");
                    nameLabel.call(wrap, nodeWidth - 5);
                }});
            }}

            function updateDetails(htmlContent) {{
                const detailsPanel = document.getElementById('details-panel');
                const detailsText = document.getElementById('details-text');
                detailsPanel.style.maxHeight = detailsPanel.scrollHeight + 'px';
                detailsText.style.opacity = 0;
                setTimeout(() => {{
                    detailsText.innerHTML = htmlContent;
                    detailsPanel.style.maxHeight = detailsPanel.scrollHeight + 'px';
                    detailsText.style.opacity = 1;
                }}, 200);
            }}

            function debounce(func, wait) {{
                let timeout;
                return function executedFunction(...args) {{
                    const later = () => {{ clearTimeout(timeout); func(...args); }};
                    clearTimeout(timeout);
                    timeout = setTimeout(later, wait);
                }};
            }}
            
            window.addEventListener('resize', debounce(() => {{
                if (isTreeRendered && !toggle.checked) renderChart();
                if (isChordRendered && toggle.checked) renderChordChart();
            }}, 250));
            
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
                    dragstarted_x = event.x; dragstarted_y = event.y;
                    d3.select(this).raise();
                }}
                function dragged(event, d) {{ d.fx = event.x; d.fy = event.y; }}
                function dragended(event, d) {{
                    if (!event.active) {{ simulation.alphaTarget(0); }}
                    d.fx = null; d.fy = null;
                    if (Math.sqrt(Math.pow(event.x - dragstarted_x, 2) + Math.pow(event.y - dragstarted_y, 2)) < 3) {{
                        updateDetails(d.description);
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
        }});
    </script>
</body>
</html>
        """
        return html_template