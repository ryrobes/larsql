import json
import os
from windlass.eddies.base import simple_eddy

@simple_eddy
def create_chart(title: str, data_points: str) -> str:
    """
    Creates a simple bar chart and returns it as an image.
    data_points should be comma-separated numbers.
    """
    # Lazy import matplotlib to avoid import errors when not installed
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: matplotlib is not installed. Install it with: pip install matplotlib"

    try:
        data = [float(x.strip()) for x in data_points.split(",")]
    except ValueError:
        return "Error: data_points must be comma-separated numbers."

    filename = "chart.png"
    abs_path = os.path.abspath(filename)

    plt.figure(figsize=(6, 4))
    plt.bar(range(len(data)), data, color='skyblue')
    plt.title(title)
    plt.xlabel('Items')
    plt.ylabel('Values')
    plt.savefig(abs_path)
    plt.close()
    
    # Return magic structure
    return json.dumps({
        "content": f"I have generated the chart '{title}' with data {data_points}.",
        "images": [abs_path]
    })