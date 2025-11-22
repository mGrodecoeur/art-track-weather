# Weather Track Visualizer in Python
# Requirements: pip install requests svg.path numpy matplotlib
# Run this script: python your_script.py
# Assumes your SVG file is 'track.svg' in the same directory.
# For complex SVGs, ensure paths are supported by svg.path.
# Interactive: Drag to rotate view, click button to load weather and update.

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import xml.etree.ElementTree as ET
from svg.path import parse_path
import requests
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

class TrackVisualizer:
    def __init__(self, svg_file='aut-info.svg', depth=5, lat=48.8566, lon=2.3522):
        self.depth = depth
        self.lat = lat
        self.lon = lon
        self.wind_speed = 0
        self.wind_direction = 0
        self.track_meshes = []
        self.particle_positions = None
        self.velocities = None
        self.particle_scatter = None

        # Parse SVG
        self.parse_svg(svg_file)

        # Setup figure
        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.ax.set_box_aspect([1,1,1])
        self.ax.view_init(elev=35, azim=-60)  # Isometric view

        # Add track meshes
        for verts, color in self.track_meshes:
            self.ax.add_collection3d(Poly3DCollection(verts, facecolors=color, edgecolors='k', alpha=0.8))

        # Particles for wind
        self.particle_count = 1000
        bounds = 100
        self.particle_positions = np.random.rand(self.particle_count, 3) * 200 - 100
        self.particle_positions[:, 1] = np.random.rand(self.particle_count) * 10  # Height
        self.velocities = np.zeros((self.particle_count, 3))
        self.particle_scatter = self.ax.scatter(self.particle_positions[:, 0], self.particle_positions[:, 1], self.particle_positions[:, 2], c='w', s=1)

        # Center and set limits
        self.center_track()
        self.ax.set_xlim(-bounds, bounds)
        self.ax.set_ylim(0, 50)  # Assuming low height
        self.ax.set_zlim(-bounds, bounds)

        # Button for weather
        self.button_ax = plt.axes([0.8, 0.025, 0.1, 0.075])
        self.button = Button(self.button_ax, 'Load Weather')
        self.button.on_clicked(self.load_weather)

        # Animation
        self.anim = FuncAnimation(self.fig, self.update, interval=20)

    def parse_svg(self, svg_file):
        tree = ET.parse(svg_file)
        root = tree.getroot()
        ns = {'svg': 'http://www.w3.org/2000/svg'}

        for path_elem in root.findall('.//svg:path', ns):
            d = path_elem.get('d')
            fill = path_elem.get('fill', '#000000')
            if fill == 'none':
                continue  # Skip unfilled

            # Parse color
            if fill.startswith('#'):
                color = tuple(int(fill[i:i+2], 16)/255 for i in (1, 3, 5))
            else:
                color = (0, 0, 0)

            # Parse path to points
            path = parse_path(d)
            points = []
            for t in np.linspace(0, 1, 100):  # Sample 100 points
                pt = path.point(t)
                points.append((pt.real, pt.imag))
            points = np.array(points)

            # Extrude
            verts = self.extrude_shape(points)
            self.track_meshes.append((verts, color))

    def extrude_shape(self, points_2d):
        # points_2d: Nx2 array
        n = len(points_2d)
        verts = []

        # Bottom face
        bottom = np.hstack((points_2d, np.zeros((n, 1))))
        verts.append(bottom.tolist())

        # Top face
        top = np.hstack((points_2d, np.full((n, 1), self.depth)))
        verts.append(top.tolist())

        # Side faces
        for i in range(n):
            j = (i + 1) % n
            side = [
                [points_2d[i, 0], points_2d[i, 1], 0],
                [points_2d[j, 0], points_2d[j, 1], 0],
                [points_2d[j, 0], points_2d[j, 1], self.depth],
                [points_2d[i, 0], points_2d[i, 1], self.depth]
            ]
            verts.append(side)

        return verts

    def center_track(self):
        all_points = np.vstack([np.vstack(vert) for vert, _ in self.track_meshes])
        center = np.mean(all_points, axis=0)
        for i, (verts, color) in enumerate(self.track_meshes):
            new_verts = [np.array(v) - center for v in verts]
            self.track_meshes[i] = (new_verts, color)

        # Update collections? Since added later, but in init after parse.

    def load_weather(self, event):
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=wind_speed_10m,wind_direction_10m"
        try:
            response = requests.get(url)
            data = response.json()
            self.wind_speed = data['current']['wind_speed_10m'] / 10  # Scale
            self.wind_direction = data['current']['wind_direction_10m']
            print(f"Wind: {self.wind_speed * 10} km/h from {self.wind_direction}°")

            # Rotate track (around Y axis)
            angle = np.deg2rad(self.wind_direction) - np.pi  # Adjust
            rot_matrix = np.array([
                [np.cos(angle), 0, np.sin(angle)],
                [0, 1, 0],
                [-np.sin(angle), 0, np.cos(angle)]
            ])
            for i, (verts, color) in enumerate(self.track_meshes):
                new_verts = [np.dot(np.array(v), rot_matrix) for v in verts]
                self.track_meshes[i] = (new_verts, color)

            # Update wind vector (along -Z after rotation)
            wind_vec = np.array([0, 0, -self.wind_speed])
            self.velocities[:] = wind_vec

            # Redraw track - clear and re-add
            self.ax.cla()
            for verts, color in self.track_meshes:
                self.ax.add_collection3d(Poly3DCollection(verts, facecolors=color, edgecolors='k', alpha=0.8))
            self.particle_scatter = self.ax.scatter(self.particle_positions[:, 0], self.particle_positions[:, 1], self.particle_positions[:, 2], c='w', s=1)
            self.center_track()  # Re-center after rotation
            plt.draw()

        except Exception as e:
            print(f"Error fetching weather: {e}")

    def update(self, frame):
        delta = 0.1
        self.particle_positions += self.velocities * delta

        # Reset out-of-bounds
        mask = np.logical_or(np.abs(self.particle_positions[:, 0]) > 100, np.abs(self.particle_positions[:, 2]) > 100)
        self.particle_positions[mask] = np.random.rand(np.sum(mask), 3) * 200 - 100
        self.particle_positions[mask, 1] = np.random.rand(np.sum(mask)) * 10

        self.particle_scatter._offsets3d = (self.particle_positions[:, 0], self.particle_positions[:, 1], self.particle_positions[:, 2])
        return self.particle_scatter,

if __name__ == "__main__":
    viz = TrackVisualizer()
    plt.show()