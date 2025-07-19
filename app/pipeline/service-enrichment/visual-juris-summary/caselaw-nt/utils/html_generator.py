import json

class HtmlGenerator:
    """
    Generates an interactive "Subway Map" HTML visualization from a legal case summary JSON object.
    """

    def generate_html_tree(self, json_data: dict) -> str:
        """
        Takes a dictionary parsed from a case summary JSON and returns a complete
        HTML string for the interactive subway map visualization.

        Args:
            json_data (dict): The case data parsed from a JSON file.

        Returns:
            str: A self-contained HTML document as a string.
        """
        # Convert the Python dictionary to a JSON string to be safely embedded in the HTML script tag.
        json_string_for_html = json.dumps(json_data)

        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Case Law Visualization - Subway Map</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Poppins', sans-serif;
            background-color: #ffffff;
            font-size: 14px;
        }}
        .station {{
            cursor: pointer;
        }}
        .station:hover .station-dot {{
            stroke: #1d4ed8; /* Change stroke color on hover */
        }}
        .station .station-dot, .station .station-label {{
            transition: all 0.2s ease-in-out;
        }}
        .station.active .station-dot {{
            fill: #1d4ed8;
            stroke: #1d4ed8;
        }}
        .station.active .station-label {{
            font-weight: 600;
            color: #1d4ed8;
        }}
        .content-card {{
            display: none;
            /* Removed background, shadow, and border for a transparent look */
            animation: fadeIn 0.5s ease-out;
        }}
        .content-card.active {{
            display: block;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .card-title {{
            font-family: 'Poppins', sans-serif;
            font-weight: 500;
        }}
        .timeline-item {{
            position: relative;
            padding-left: 2.5rem;
            padding-bottom: 1.5rem;
        }}
        .timeline-item:last-child {{ padding-bottom: 0; }}
        .timeline-dot {{
            position: absolute;
            left: 0;
            top: 0.25rem;
            height: 0.75rem; /* 12px */
            width: 0.75rem; /* 12px */
            background-color: white;
            border: 2px solid #9ca3af;
            border-radius: 50%;
        }}
        .timeline-line {{
            position: absolute;
            left: 0.3125rem; /* 5px */
            top: 0.75rem; /* 12px */
            bottom: 0;
            width: 2px;
            background-color: #e5e7eb; /* Lighter grey */
        }}
        .timeline-item:last-child .timeline-line {{ display: none; }}
    </style>
</head>
<body class="bg-white p-4 md:p-8">

    <div class="w-full max-w-4xl mx-auto flex flex-col md:flex-row gap-2">
        <!-- Subway Map Navigator -->
        <div class="w-full md:w-1/3 lg:w-1/4">
            <svg id="subway-map" width="100%" height="450"></svg>
        </div>

        <!-- Content Display Area -->
        <div id="content-area" class="w-full md:w-2/3 lg:w-3/4" style="margin-top: 18px;">
            <!-- Content cards will be injected here -->
        </div>
    </div>

    <script>
    const caseData = {json_string_for_html};

    document.addEventListener('DOMContentLoaded', () => {{
        const svg = document.getElementById('subway-map');
        const contentArea = document.getElementById('content-area');
        const totalCards = caseData.cards.length;
        const yStep = 60;
        const xPos = 20;

        // Draw the main line
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', xPos);
        line.setAttribute('y1', yStep);
        line.setAttribute('x2', xPos);
        line.setAttribute('y2', yStep * totalCards);
        line.setAttribute('stroke', '#e5e7eb'); /* Lighter grey */
        line.setAttribute('stroke-width', '2');
        svg.appendChild(line);

        caseData.cards.forEach((card, index) => {{
            // Create Station on Map
            const yPos = yStep * (index + 1);
            const stationGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            stationGroup.classList.add('station');
            stationGroup.dataset.index = index;

            const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            dot.classList.add('station-dot');
            dot.setAttribute('cx', xPos);
            dot.setAttribute('cy', yPos);
            dot.setAttribute('r', '6');
            dot.setAttribute('fill', 'white');
            dot.setAttribute('stroke', '#9ca3af');
            dot.setAttribute('stroke-width', '2');
            
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.classList.add('station-label');
            label.setAttribute('x', xPos + 20);
            label.setAttribute('y', yPos);
            label.setAttribute('dy', '0.35em');
            label.textContent = card.menuLabel;

            stationGroup.appendChild(dot);
            stationGroup.appendChild(label);
            svg.appendChild(stationGroup);

            // Create Content Card
            const contentCard = document.createElement('div');
            contentCard.className = 'content-card rounded-xl'; // Removed bg-white
            contentCard.dataset.index = index;
            contentCard.innerHTML = generateCardHTML(card);
            contentArea.appendChild(contentCard);
        }});

        const stations = document.querySelectorAll('.station');
        const contentCards = document.querySelectorAll('.content-card');

        function switchStation(index) {{
            stations.forEach(s => s.classList.remove('active'));
            contentCards.forEach(c => c.classList.remove('active'));

            stations[index].classList.add('active');
            contentCards[index].classList.add('active');
        }}

        stations.forEach((station, index) => {{
            station.addEventListener('click', () => switchStation(index));
        }});

        // Activate the first station by default
        switchStation(0);
    }});

    function generateCardHTML(card) {{
        let contentHTML = '';
        switch (card.type) {{
            case 'overview':
                const listItems = card.content.map(item => `
                    <li class="flex items-start text-sm">
                        <span class="font-semibold w-28 shrink-0">${{item.label}}:</span> 
                        <span class="text-gray-600">${{item.value}}</span>
                    </li>`).join('');
                const highlightColor = card.highlight.status === 'negative' ? 'red' : 'green';
                contentHTML = `
                    <ul class="space-y-3 text-gray-800">${{listItems}}</ul>
                    <div class="bg-${{highlightColor}}-50 p-4 border-t border-${{highlightColor}}-200 mt-4">
                         <p class="text-sm font-semibold text-${{highlightColor}}-800 text-center">${{card.highlight.text}}</p>
                    </div>`;
                break;
            case 'list':
                const listContent = card.content.map(item => {{
                    const itemClass = item.highlight ? 'font-semibold text-gray-800 bg-gray-100 p-3 rounded-md' : '';
                    return `<li class="${{itemClass}}">${{item.text}}</li>`;
                }}).join('');
                contentHTML = `<ul class="space-y-3 text-gray-600 list-disc list-inside text-sm">${{listContent}}</ul>`;
                break;
            case 'timeline':
                const timelineItems = card.content.map(item => {{
                    const textColor = item.highlight ? 'text-blue-800' : 'text-gray-800';
                    return `
                        <div class="timeline-item">
                            <div class="timeline-line"></div>
                            <div class="timeline-dot" style="border-color: ${{item.highlight ? '#1e40af' : ''}};"></div>
                            <p class="font-semibold text-sm ${{textColor}}">${{item.date}}</p>
                            <p class="text-xs text-gray-500">${{item.event || item.description}}</p>
                        </div>`;
                }}).join('');
                contentHTML = `<div>${{timelineItems}}</div>`;
                break;
            case 'comparison':
                const sideA = card.content.sideA;
                const sideB = card.content.sideB;
                contentHTML = `
                    <div class="grid md:grid-cols-2 gap-4">
                        <div>
                            <h3 class="font-semibold text-blue-800 text-sm">${{sideA.title}}</h3>
                            <p class="mt-1 text-gray-600 text-xs">${{sideA.text}}</p>
                        </div>
                        <div>
                            <h3 class="font-semibold text-blue-800 text-sm">${{sideB.title}}</h3>
                            <p class="mt-1 text-gray-600 text-xs">${{sideB.text}}</p>
                        </div>
                    </div>`;
                break;
            case 'principle':
                const bodyItems = card.content.body.map(p => `<p class="mt-2 text-gray-600">${{p}}</p>`).join('');
                contentHTML = `
                    <div class="text-sm">
                        <h3 class="font-semibold text-base text-gray-900">${{card.content.title}}</h3>
                        ${{bodyItems}}
                    </div>`;
                break;
            case 'scorecard':
                const scorecardItems = card.content.map(item => {{
                    let bulletPoint = '';
                    if (item.status === 'negative') {{
                        bulletPoint = `<div class="w-2 h-2 bg-gray-700 rounded-full mt-1.5 mr-3 flex-shrink-0"></div>`;
                    }} else {{ // Fallback for positive status
                        bulletPoint = `<div class="w-2 h-2 bg-green-500 rounded-full mt-1.5 mr-3 flex-shrink-0"></div>`;
                    }}
                    return `<li class="flex items-start text-gray-700">${{bulletPoint}}<span>${{item.text}}</span></li>`;
                }}).join('');
                contentHTML = `<ul class="space-y-3">${{scorecardItems}}</ul>`;
                break;
            case 'text':
                contentHTML = `<div class="text-gray-600 space-y-3 text-sm leading-relaxed"><p>${{card.content}}</p></div>`;
                break;
        }}

        return `
            <div class="p-6">
                <div class="flex items-start justify-between">
                    <h2 class="card-title text-lg font-medium text-gray-800">${{card.title}}</h2>
                </div>
                <div class="mt-4">${{contentHTML}}</div>
            </div>
        `;
    }}
    </script>
</body>
</html>
        """
        return html_template

