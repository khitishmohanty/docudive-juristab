import json

class HtmlGenerator:
    """
    Generates an interactive HTML tree visualization from a JurisMap JSON object.
    """

    def generate_html_tree(self, json_data: dict) -> str:
        """
        Takes a dictionary parsed from the JurisMap JSON and returns a complete
        HTML string for the interactive tree visualization.

        Args:
            json_data (dict): The case data parsed from a JSON file.

        Returns:
            str: A self-contained HTML document as a string.
        """
        case_title = json_data.get("case_title", "JurisMap Visualization")
        json_string_for_html = json.dumps(json_data)

        # FIX: Escaped all JavaScript template literals (e.g., ${...}) by doubling
        # the curly braces (e.g., ${{...}}) so the Python f-string ignores them.
        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{case_title}</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #f8f9fa;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        h1 {{
            color: #343a40;
            font-weight: 300;
        }}
        .chart-container {{
            display: flex;
            flex-direction: row;
            align-items: flex-start;
            gap: 40px;
            width: 100%;
            max-width: 1600px;
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
            color: #495057;
            border-bottom: 1px solid #dee2e6;
            padding-bottom: 10px;
        }}
        .details-panel p {{
            color: #6c757d;
            font-size: 14px;
            line-height: 1.5;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 10px;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 10px;
        }}
        .node circle {{
            stroke: #fff;
            stroke-width: 2px;
            cursor: pointer;
            transition: transform 0.2s ease-in-out;
        }}
        .node:hover circle {{
            transform: scale(1.1);
        }}
        .node text {{
            font-size: 12px;
            text-anchor: middle;
            fill: #333;
        }}
        .node .type-label {{
            font-size: 14px;
            font-weight: bold;
            fill: white;
            text-anchor: middle;
            pointer-events: none;
        }}
        .link {{
            fill: none;
            stroke: #ccc;
            stroke-width: 1.5px;
        }}
        .level-label {{
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
            fill: #adb5bd;
        }}
        .level-line {{
            stroke: #e9ecef;
            stroke-dasharray: 4, 4;
        }}
    </style>
</head>
<body>
    <h1>{case_title}</h1>
    <div class="chart-container">
        <div class="tree-container">
            <svg id="tree-svg"></svg>
        </div>
        <div class="sidebar">
            <div class="details-panel" id="details-panel">
                <h3>Details</h3>
                <p id="details-text">Select a person on the map to see more details here.</p>
            </div>
            <div class="legend-panel" id="legend-panel">
                <h3>Colour Legends</h3>
            </div>
        </div>
    </div>

    <script>
        const data = {json_string_for_html};

        const colorMap = {{
            'Judiciary': '#6f42c1',
            'Prosecution': '#fd7e14',
            'Plaintiff': '#fd7e14',
            'Defendant': '#0d6efd',
            'Accused': '#0d6efd',
            'Victim': '#20c997',
            'Co-offender': '#dc3545',
            'Third Party': '#ffc107',
            'Insurer': '#6610f2',
            'Intervener': '#17a2b8',
            'Legal Representative': '#0dcaf0',
            'Legal Firm': '#0dcaf0',
            'Other parties': '#6c757d'
        }};
        
        const legendPanel = document.getElementById('legend-panel');
        Object.entries(colorMap).forEach(([type, color]) => {{
            const item = document.createElement('div');
            item.className = 'legend-item';
            item.innerHTML = `<div class="legend-color" style="background-color: ${{color}};"></div><span>${{type}}</span>`;
            legendPanel.appendChild(item);
        }});

        const width = document.querySelector('.tree-container').clientWidth;
        const height = 800;
        const svg = d3.select("#tree-svg").attr("width", width).attr("height", height);
        const g = svg.append("g");

        const zoom = d3.zoom().on("zoom", (event) => {{
            g.attr("transform", event.transform);
        }});
        svg.call(zoom);

        const nodes = [];
        const nodeMap = new Map();
        const levelY = new Map();
        let yPos = 100;

        data.levels.forEach(level => {{
            levelY.set(level.level_number, yPos);
            level.parties.forEach(party => {{
                const node = {{
                    id: party.name,
                    ...party,
                    y: yPos,
                    x: 0
                }};
                nodes.push(node);
                nodeMap.set(party.name, node);
            }});
            yPos += 180;
        }});
        
        levelY.forEach((y, levelNumber) => {{
            const levelNodes = nodes.filter(n => n.y === y);
            const levelWidth = width / (levelNodes.length + 1);
            levelNodes.forEach((node, i) => {{
                node.x = levelWidth * (i + 1);
            }});
        }});

        const links = data.connections.map(d => {{
            const source = nodeMap.get(d.source);
            const target = nodeMap.get(d.target);
            return {{ source, target, relationship: d.relationship }};
        }}).filter(l => l.source && l.target);

        levelY.forEach((y, levelNumber) => {{
            const levelData = data.levels.find(l => l.level_number === levelNumber);
            g.append("text")
                .attr("x", 50)
                .attr("y", y - 60)
                .attr("class", "level-label")
                .text(levelData.level_description);

            g.append("line")
                .attr("x1", 50)
                .attr("x2", width - 50)
                .attr("y1", y - 50)
                .attr("y2", y - 50)
                .attr("class", "level-line");
        }});

        const link = g.append("g")
            .selectAll("path")
            .data(links)
            .join("path")
            .attr("class", "link")
            .attr("d", d => `M${{d.source.x}},${{d.source.y}} C ${{d.source.x}},${{(d.source.y + d.target.y) / 2}} ${{d.target.x}},${{(d.source.y + d.target.y) / 2}} ${{d.target.x}},${{d.target.y}}`);

        const node = g.append("g")
            .selectAll("g")
            .data(nodes)
            .join("g")
            .attr("class", "node")
            .attr("transform", d => `translate(${{d.x}},${{d.y}})` )
            .on("click", (event, d) => {{
                document.getElementById('details-text').textContent = d.description;
            }});

        node.append("circle")
            .attr("r", 25)
            .attr("fill", d => colorMap[d.type] || colorMap['Other parties']);
        
        node.append("text")
            .attr("class", "type-label")
            .attr("dy", "0.35em")
            .text(d => d.type.substring(0, 1));

        node.append("text")
            .attr("dy", "40px")
            .text(d => d.name);
            
    </script>
</body>
</html>
        """
        return html_template
