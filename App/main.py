# Imports
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy_garden.mapview import MapView, MapMarker
from geopy.geocoders import Nominatim
import ssl
import certifi
from threading import Thread
import geopy.geocoders
from kivy.core.window import Window
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.metrics import dp
import json
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.core.clipboard import Clipboard
import random
from kivy.utils import platform
from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
import traceback
import requests

if platform == 'android':
    try:
        from jnius import PythonJavaClass, java_method, autoclass
        from android.permissions import request_permissions, Permission
        from android.broadcast import BroadcastReceiver
        from notification import AndroidNotification
    except ImportError as e:
        print(f"Android modules not available: {e}")
        # Fallback definitions for desktop testing
        autoclass = None
        BroadcastReceiver = None
        AndroidNotification = None

# Categories for anonymized location search.
# Used for filtering specific public places with Overpass API.# 🔧 NEW: Categories for anonymized location search
PLACE_CATEGORIES = {
    "Dining": [
        '"amenity"="restaurant"',
        '"amenity"="cafe"',
        '"amenity"="bar"',
        '"amenity"="fast_food"'
    ],
    "Shopping": [
        '"shop"="supermarket"',
        '"shop"="bakery"',
        '"shop"="convenience"'
    ],
    "Healthcare": [
        '"amenity"="pharmacy"'
    ],
    "Services": [
        '"amenity"="bank"',
        '"amenity"="atm"',
        '"amenity"="post_office"',
        '"amenity"="fuel"'
    ],
    "Transport": [
        '"highway"="bus_stop"'
    ],
    "Recreation": [
        '"leisure"="park"',
        '"shop"="hairdresser"'
    ]
}


def determine_category_from_tags(tags):
    """
    Determines a location's category based on its OSM tags.
    Returns a human-readable category string.
    """
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    leisure = tags.get("leisure", "")
    highway = tags.get("highway", "")

    if amenity in ["restaurant", "cafe", "bar", "fast_food"]:
        return "Dining"
    elif shop in ["supermarket", "bakery", "convenience"]:
        return "Shopping"
    elif amenity == "pharmacy":
        return "Healthcare"
    elif amenity in ["bank", "atm", "post_office", "fuel"]:
        return "Services"
    elif highway == "bus_stop":
        return "Transport"
    elif leisure == "park" or shop == "hairdresser":
        return "Recreation"
    else:
        return "Other"


def is_valid_address(address, tags):
    """
    Checks if an address is valid.
    """
    return address is not None and len(address.strip()) > 0


def get_places_with_fallback(api, location, radius=500):
    """
    Fetches nearby public places by direct HTTP request to Overpass API.
    This method bypasses the Overpass Python library.
    Returns a list of amenities with address and coordinates.
    """

    print(f"Direct HTTP request to Overpass API...")

    # Compose Overpass query for various amenities
    overpass_query = f"""
[out:json][timeout:25];
(
  node(around:{radius},{location.latitude},{location.longitude})[amenity=restaurant];
  node(around:{radius},{location.latitude},{location.longitude})[amenity=cafe];
  node(around:{radius},{location.latitude},{location.longitude})[amenity=bank];
  node(around:{radius},{location.latitude},{location.longitude})[shop=supermarket];
  node(around:{radius},{location.latitude},{location.longitude})[amenity=pharmacy];
);
out body;
"""

    try:
        url = "https://overpass-api.de/api/interpreter"
        response = requests.post(url, data={'data': overpass_query.strip()}, timeout=30)

        if response.status_code != 200:
            print(f"HTTP Error: {response.status_code}")
            return []

        data = response.json()
        elements = data.get('elements', [])
        print(f"Direct API: {len(elements)} elements found")

        amenities_data = []

        for element in elements:
            try:
                # Extract coordinates
                lat = element.get('lat')
                lon = element.get('lon')
                if not (lat and lon):
                    continue

                # Extract tags
                tags = element.get('tags', {})
                if not tags:
                    continue

                # Check address
                street = tags.get("addr:street", "")
                city = tags.get("addr:city", "")

                if street and city:
                    address = f"{street}, {city}"

                    # Determine category
                    amenity = tags.get('amenity', '')
                    shop = tags.get('shop', '')
                    category = amenity or shop or 'Unknown'

                    amenities_data.append({
                        'address': address,
                        'coordinates': (lon, lat),
                        'category': category,
                        'tags': tags
                    })
                    print(f"HTTP Address: {address} ({category})")

                    # Limit number of returned amenities
                    if len(amenities_data) >= 10:
                        break

            except Exception as e:
                print(f"Element error: {e}")
                continue

        print(f"Direct API result: {len(amenities_data)} addresses")
        return amenities_data

    except Exception as e:
        print(f"HTTP request error: {e}")
        return []


def test_simple_overpass(api, location):
    """
    Sends a basic test query to Overpass API to check if it's reachable and functional.
    Returns True if at least one restaurant is found, otherwise False.
    """
    try:
        url = "https://overpass-api.de/api/interpreter"
        simple_query = f"""
        [out:json][timeout:25];
        node(around:500,{location.latitude},{location.longitude})[amenity=restaurant];
        out body;
        """

        response = requests.post(url, data={'data': simple_query}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            elements = data.get('elements', [])
            return len(elements) > 0
        else:
            print(f"Direct HTTP failed: {response.status_code}")
            return False

    except Exception as e:
        print(f"HTTP Test Error: {e}")
        return False


def extract_address_from_tags(tags):
    """
    Extracts a full, real address from OSM tags.
    Only returns addresses if 'street' and 'city' are present.
    Ignores names, brands, and generic types.
    """
    street = tags.get("addr:street", "").strip()
    housenumber = tags.get("addr:housenumber", "").strip()
    postcode = tags.get("addr:postcode", "").strip()
    city = tags.get("addr:city", "").strip()

    if street and city:
        address_parts = []

        # Add street and optional house number
        if housenumber:
            address_parts.append(f"{street} {housenumber}")
        else:
            address_parts.append(street)

        # Add postal code and city
        if postcode:
            address_parts.append(f"{postcode} {city}")
        else:
            address_parts.append(city)

        result = ", ".join(address_parts)
        print(f"Real address accepted: {result}")
        return result

    # 🔧 DISCARD EVERYTHING ELSE - even if name, brand, operator are present
    print(f"Discarded (no complete address): {tags.get('name', 'Unknown')}")
    return None


# MapLegend: Displays a legend for the map with colored squares representing location types
class MapLegend(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint = (None, None)
        self.size = (dp(165), dp(80))
        self.spacing = dp(8)
        self.padding = (dp(12), dp(10), dp(12), dp(10))

        # Draw background rectangle and border
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.bg_rect = Rectangle(size=self.size, pos=self.pos)

        self.bind(size=self._update_bg, pos=self._update_bg)

        # Generated location legend entry
        new_location_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(25),
            spacing=dp(10)
        )

        new_location_square_container = AnchorLayout(
            anchor_x='center',
            anchor_y='center',
            size_hint=(None, 1),
            width=dp(16)
        )
        new_location_square = self._create_color_square((1.0, 0.0, 0.0, 1.0))  # Pure red
        new_location_square_container.add_widget(new_location_square)

        new_location_label = Label(
            text="Generated Location",
            size_hint_x=1,
            color=(0, 0, 0, 1),
            font_size='13sp',
            halign="left",
            valign="middle"
        )
        new_location_label.bind(size=new_location_label.setter('text_size'))

        new_location_layout.add_widget(new_location_square_container)
        new_location_layout.add_widget(new_location_label)
        self.add_widget(new_location_layout)

        # Original location legend entry
        old_location_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(25),
            spacing=dp(10)
        )

        old_location_square_container = AnchorLayout(
            anchor_x='center',
            anchor_y='center',
            size_hint=(None, 1),
            width=dp(16)
        )
        old_location_square = self._create_color_square((0.6, 0.0, 0.0, 1.0))
        old_location_square_container.add_widget(old_location_square)

        old_location_label = Label(
            text="Original Location",
            size_hint_x=1,
            color=(0, 0, 0, 1),
            font_size='13sp',
            halign="left",
            valign="middle"
        )
        old_location_label.bind(size=old_location_label.setter('text_size'))

        old_location_layout.add_widget(old_location_square_container)
        old_location_layout.add_widget(old_location_label)
        self.add_widget(old_location_layout)

    def _create_color_square(self, color):
        """Creates a colored square for the legend"""

        class ColorSquare(BoxLayout):
            def __init__(self, color, **kwargs):
                super().__init__(**kwargs)
                self.square_color = color
                self.size_hint = (None, None)
                self.size = (dp(16), dp(16))
                self.bind(size=self.draw_square, pos=self.draw_square)
                Clock.schedule_once(lambda dt: self.draw_square(), 0.1)

            def draw_square(self, *args):
                self.canvas.clear()
                with self.canvas:
                    Color(*self.square_color)
                    Rectangle(size=self.size, pos=self.pos)

        return ColorSquare(color)

    def _update_bg(self, instance, value):
        # Update background and border when widget size/position changes
        self.canvas.before.clear()
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.bg_rect = Rectangle(size=self.size, pos=self.pos)
            Color(0.7, 0.7, 0.7, 1)
            Line(rectangle=(self.pos[0], self.pos[1], self.size[0], self.size[1]), width=1)


# InfoPopup: Popup window displaying app information and usage instructions
class InfoPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "App Information"
        self.size_hint = (0.9, 0.8)
        self.title_color = (0, 0, 0, 1)
        self.auto_dismiss = True
        self.background = ""
        self.background_color = (1, 1, 1, 1)

        # Main layout for popup content
        layout = BoxLayout(
            orientation="vertical",
            padding=(dp(8), dp(15), dp(8), dp(15)),
            spacing=dp(15)
        )

        # Info text displayed in the popup
        info_text = """
[b]DeLocator[/b]
[color=666666]Privacy-First Location Anonymizer - Version 1.0[/color]

[b]PURPOSE OF THE APP[/b]
Prevent the disclosure of sensitive or private addresses (e.g., home address, work address, etc.) to third-party apps and online platforms. For example, you can use the anonymized location instead of the real location for navigation purposes (e.g., Google Maps).

[b]WHAT IT DOES[/b]
Transforms your real address into a random nearby public location within 500m radius for enhanced privacy protection.

[b]HOW IT WORKS[/b]
[b]Step 1: ENTER ADDRESS[/b] - App geocodes your location using OpenStreetMap
[b]Step 2: FIND CANDIDATES[/b] - Searches for 10-15 public places in 6 categories nearby
[b]Step 3: RANDOM SELECTION[/b] - Picks one anonymized location randomly

[color=666666][b]Practical Example for Step 3:[/b]
Instead of sharing "123 Main Street, Your Home", the app might randomly select "Central Library, 456 Oak Avenue" or "City Pharmacy, 789 Pine Street" - both real public places near your actual location. You can then use this anonymized address for delivery apps, ride-sharing, or any service where you don't want to reveal your exact address.[/color]

[b]Step 4: SAVE & REUSE[/b] - Store up to 3 favorites for consistent mapping

[b]PRIVACY FEATURES[/b]
[b]Non-deterministic anonymization[/b] - Different results each time for unsaved addresses
[b]Local storage only[/b] - No personal data sent to external servers
[b]OpenStreetMap integration[/b] - Uses only verified public place data
[b]Clipboard integration[/b] - Quick copy functionality with notifications

[b]EFFECTS OF ANONYMIZATION[/b]
Please note that the anonymized location will be further away from your real location (within 500 meters), and this may impact the accuracy depending on the usage purpose. Consider this distance when using the anonymized address for time-sensitive deliveries or precise navigation requirements.

[b]SUPPORTED CATEGORIES[/b]
[color=0066cc]Restaurants & Cafes[/color]    [color=0066cc]Shops & Markets[/color]
[color=0066cc]Health & Pharmacy[/color]     [color=0066cc]Transport Stops[/color]
[color=0066cc]Banks & Services[/color]      [color=0066cc]Parks & Recreation[/color]

[b]TECHNICAL SPECIFICATIONS[/b]
[b]Platform:[/b] Android API 21+
[b]Framework:[/b] Python with Kivy
[b]APIs:[/b] Nominatim (Geocoding) + Overpass (POI Data)
[b]Permissions:[/b] Internet, Network State, Notifications
[b]Storage:[/b] Local JSON files only

[b]ABOUT THE DEVELOPER[/b]
This application was developed by [b]Aldina Kovacevic[/b] as part of a Master's thesis research project focusing on location privacy and data anonymization techniques.

[b]Development Period:[/b] 2024-2025
[b]Last Update:[/b] June 22, 2025
[b]Research Focus:[/b] Privacy-preserving location services

[b]SUPPORT & FEEDBACK[/b]
For technical support, feature requests, or research inquiries, please feel free to reach out.

This application demonstrates practical approaches to location privacy while maintaining usability for everyday location sharing needs.

[color=4169E1][b]Thank you for contributing to privacy-aware location sharing![/b][/color]"""

        self.info_label = Label(
            text=info_text,
            markup=True,
            color=(0.1, 0.1, 0.1, 1),
            halign="left",
            valign="top",
            size_hint_y=None,
            text_size=(None, None)
        )

        self.info_label.bind(texture_size=self.info_label.setter('size'))

        # ScrollView for handling long info text on mobile
        self.scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(8),
            scroll_type=['content'],
            smooth_scroll_end=10
        )
        self.scroll.add_widget(self.info_label)
        layout.add_widget(self.scroll)

        # Close button for dismissing the popup
        close_button = Button(
            text="Close",
            size_hint=(1, None),
            height=dp(60),
            background_color=(0.3, 0.6, 0.9, 1),
            background_normal="",
        )
        close_button.bind(on_release=self.dismiss)
        layout.add_widget(close_button)

        self.content = layout

        # Dynamically update text width for better mobile compatibility
        def update_text_width(instance, value):
            scroll_width = self.scroll.width if hasattr(self, 'scroll') and self.scroll.width > 0 else layout.width
            total_padding = dp(8) + dp(8) + dp(5) + dp(10)
            available_width = max(dp(250), scroll_width - total_padding)
            self.info_label.text_size = (available_width, None)

        layout.bind(size=update_text_width)
        self.bind(size=update_text_width)
        self.scroll.bind(size=update_text_width)

        Clock.schedule_once(lambda dt: update_text_width(None, None), 0.1)
        Clock.schedule_once(lambda dt: update_text_width(None, None), 0.3)
        Clock.schedule_once(lambda dt: update_text_width(None, None), 0.5)


# SavePopup: Popup for saving a location with description and icon selection
class SavePopup(Popup):
    address = StringProperty()
    original_address = StringProperty()
    selected_icon = StringProperty(None)
    icon_buttons = {}

    def __init__(self, original_address, address, **kwargs):
        super().__init__(**kwargs)
        self.original_address = original_address
        self.address = address
        self.title = "Save Location"

        # Set popup size based on window size
        popup_width = min(Window.width * 0.95, dp(600))
        popup_height = Window.height * 0.6

        self.size_hint = (None, None)
        self.size = (popup_width, popup_height)
        self.title_color = (0, 0, 0, 1)
        self.auto_dismiss = False
        self.background = ""
        self.background_color = (1, 1, 1, 1)

        # Main layout for content
        layout = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(15))

        # Display the original and generated address
        self.address_label = Label(
            text=f"Original: {self.original_address}\n\n[b]Generated: {self.address}[/b]",
            markup=True,
            size_hint_y=None,
            halign="center",
            valign="middle",
            color=(0, 0, 0, 1),
            text_size=(popup_width - dp(40), None)
        )
        self.address_label.bind(
            texture_size=lambda instance, value: setattr(instance, "height", value[1] + dp(20))
        )
        layout.add_widget(self.address_label)

        icon_layout = BoxLayout(orientation="horizontal", spacing=dp(15), size_hint_y=None, height=dp(70))

        # Icon selection layout
        icons = {
            "Home": "icons/home.png",
            "Work": "icons/work.png",
            "Family": "icons/family.png"
        }

        for name, icon_path in icons.items():
            btn = Button(
                size_hint=(None, None),
                size=(dp(40), dp(40)),
                background_normal=icon_path,
                background_down=icon_path,
                background_color=(1, 1, 1, 1),
                border=(5, 5, 5, 5)
            )
            btn.bind(on_release=lambda btn, path=icon_path: self.select_icon(btn, path))
            self.icon_buttons[icon_path] = btn
            icon_layout.add_widget(btn)

        layout.add_widget(icon_layout)

        # Description input field
        self.description_input = TextInput(
            hint_text="Enter description",
            multiline=False,
            size_hint_y=None,
            height=dp(50),
            background_normal='',
            background_active='',
            background_color=(0.95, 0.95, 0.95, 1),
            foreground_color=(0.1, 0.1, 0.1, 1),
            padding=(dp(10), dp(10)),
            hint_text_color=(0.5, 0.5, 0.5, 1),
            font_size='16sp'
        )
        layout.add_widget(self.description_input)

        # Buttons for canceling and saving the location
        button_layout = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(50))

        cancel_button = Button(
            text="Cancel",
            size_hint=(0.5, 1),
            background_color=(0.8, 0.2, 0.2, 1),
            background_normal=""
        )
        cancel_button.bind(on_release=self.dismiss)

        save_button = Button(
            text="Save",
            size_hint=(0.5, 1),
            background_color=(0.1, 0.7, 0.3, 1),
            background_normal=""
        )
        save_button.bind(on_press=lambda instance: self.save_location())

        button_layout.add_widget(cancel_button)
        button_layout.add_widget(save_button)
        layout.add_widget(button_layout)

        self.content = layout

    def select_icon(self, button, icon_path):
        # Highlight the selected icon
        self.selected_icon = icon_path

        for btn in self.icon_buttons.values():
            btn.canvas.after.clear()
            btn.background_color = (1, 1, 1, 1)

        with button.canvas.after:
            Color(0.3, 0.6, 0.9, 1)
            Line(rectangle=(button.x, button.y, button.width, button.height), width=3)

    def save_location(self):
        # Save the location with icon, address, and description
        if not self.selected_icon:
            warning_popup = Popup(
                title="Icon Required",
                title_color=(0, 0, 0, 1),
                content=Label(text="Please select an icon before saving!", color=(1, 0, 0, 1)),
                size_hint=(0.8, 0.2),
                background="",
                background_color=(1, 1, 1, 1),
                auto_dismiss=True
            )
            warning_popup.open()
            return

        saved_locations = load_saved_locations()

        for location in saved_locations:
            if location["icon"] == self.selected_icon:
                self.ask_overwrite(location, saved_locations)
                return

        self.save_new_location(saved_locations)

    def ask_overwrite(self, existing_location, saved_locations):
        # Ask the user if they want to overwrite an existing location for the icon
        def overwrite(instance):
            saved_locations.remove(existing_location)
            self.save_new_location(saved_locations)
            confirm_popup.dismiss()

        def cancel(instance):
            confirm_popup.dismiss()

        popup_width = min(Window.width * 0.9, dp(500))

        confirm_popup = Popup(
            title="Overwrite Icon?",
            content=BoxLayout(orientation="vertical", spacing=dp(40), padding=dp(40)),
            size_hint=(None, None),
            size=(popup_width, dp(300)),
            title_color=(0, 0, 0, 1),
            auto_dismiss=False,
            background="",
            background_color=(1, 1, 1, 1)
        )

        content = confirm_popup.content

        overwrite_label = Label(
            text=f"The icon is already linked to:\n[b]{existing_location['address']}[/b]\nDo you want to overwrite it?",
            markup=True,
            color=(0, 0, 0, 1),
            halign="center",
            valign="middle",
            text_size=(popup_width - dp(80), None)
        )
        content.add_widget(overwrite_label)

        button_layout = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(50))

        yes_button = Button(text="Yes", background_color=(0.1, 0.7, 0.3, 1), size_hint=(0.5, 1))
        yes_button.bind(on_release=overwrite)

        no_button = Button(text="No", background_color=(0.8, 0.2, 0.2, 1), size_hint=(0.5, 1))
        no_button.bind(on_release=cancel)

        button_layout.add_widget(yes_button)
        button_layout.add_widget(no_button)
        content.add_widget(button_layout)

        confirm_popup.open()

    def save_new_location(self, saved_locations):
        # Actually save the new location and refresh broadcast receiver on Android
        description = self.description_input.text
        saved_locations.append({
            "original_address": self.original_address,
            "address": self.address,
            "description": description,
            "icon": self.selected_icon
        })
        save_saved_locations(saved_locations)

        if platform == "android":
            app = App.get_running_app()
            print(f"Re-registering BroadcastReceiver after Save (now {len(saved_locations)} locations)...")

            if hasattr(app, 'copy_receiver') and app.copy_receiver is not None:
                try:
                    ctx = autoclass('org.kivy.android.PythonActivity').mActivity
                    java_receiver = app.copy_receiver.receiver
                    ctx.unregisterReceiver(java_receiver)
                    print("Old BroadcastReceiver unregistered")
                except Exception as e:
                    print(f"Error unregistering old receiver: {e}")

            app.register_broadcast_receiver()

        print(
            f"Location '{self.address}' saved with description: '{description}' and icon: {self.selected_icon}")
        self.dismiss()


# MapWithMarker: Main widget for location input, map display, and location anonymization
class MapWithMarker(BoxLayout):
    def __init__(self, **kwargs):
        super(MapWithMarker, self).__init__(**kwargs)
        self.original_address = ""
        self.orientation = 'vertical'
        self.padding = dp(20)

        # Draw background
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.rect = Rectangle(size=self.size, pos=self.pos)

        self.bind(size=self._update_rect, pos=self._update_rect)

        # Address input and copy/save buttons
        self.address_input = TextInput(
            hint_text='Enter Address',
            size_hint=(0.7, None),
            height=dp(50),
            multiline=False,
            background_normal='',
            background_active=''
        )

        self.copy_button = Button(text='Copy', size_hint=(None, None), size=(dp(50), dp(50)),
                                  background_color=(0.1, 0.7, 0.3, 1), background_normal='', background_down='')
        self.copy_button.bind(on_press=self.copy_text)

        self.save_button = Button(text='Save', size_hint=(None, None), size=(dp(50), dp(50)),
                                  background_color=(0.3, 0.6, 0.9, 1), background_normal='', background_down='')
        self.save_button.bind(on_press=self.open_save_popup)

        input_layout = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(50))
        input_layout.add_widget(self.address_input)
        input_layout.add_widget(self.copy_button)
        input_layout.add_widget(self.save_button)

        # Back button for returning to start screen
        back_layout = AnchorLayout(anchor_x='left', anchor_y='top', size_hint=(None, None), size=(dp(50), dp(50)))
        back_button = Button(background_normal='icons/arrow.png', background_down='icons/arrow.png',
                             size_hint=(None, None),
                             size=(dp(50), dp(50)), background_color=(0.3, 0.6, 0.9, 1))
        back_button.bind(on_press=self.go_to_start)
        back_layout.add_widget(back_button)
        self.add_widget(back_layout)

        # Submit button for starting location anonymization
        self.submit_button = Button(text='Submit', size_hint=(1, None), height=dp(50),
                                    background_color=(0.1, 0.7, 0.3, 1), background_normal='', background_down='')
        self.submit_button.bind(on_press=self.show_map)

        # MapView and markers for displaying original and generated locations
        self.mapview = MapView(zoom=15, lat=0, lon=0, size_hint=[1, 0.8])
        self.marker_new_address = MapMarker(lat=0, lon=0, color=(1, 0, 0, 1))
        self.mapview.add_widget(self.marker_new_address)
        self.marker_old_address = MapMarker(lat=0, lon=0, color=(0.6, 0.0, 0.0, 1.0))
        self.mapview.add_widget(self.marker_old_address)
        self.mapview.opacity = 0

        # Map legend widget
        self.map_legend = MapLegend(
            size_hint=(None, None),
            size=(dp(160), dp(80)),
            opacity=0
        )

        self.add_widget(input_layout)
        self.add_widget(self.submit_button)
        self.add_widget(self.mapview)

    def show_legend(self):
        # Show the legend widget on the map
        if self.map_legend not in self.mapview.children:
            self.mapview.add_widget(self.map_legend)

        def position_legend(*args):
            self.map_legend.pos = (
                self.mapview.right - self.map_legend.width - dp(10),
                self.mapview.top - self.map_legend.height - dp(10)
            )

        self.mapview.bind(pos=position_legend, size=position_legend)
        position_legend()

        def animate_legend(dt):
            if self.map_legend.opacity < 1:
                self.map_legend.opacity = min(1, self.map_legend.opacity + 0.1)
                Clock.schedule_once(animate_legend, 0.05)

        animate_legend(0)
        print("Map Legend displayed")

    def hide_legend(self):
        # Hide the legend widget with a fade-out animation
        def animate_legend_hide(dt):
            if self.map_legend.opacity > 0:
                self.map_legend.opacity = max(0, self.map_legend.opacity - 0.1)
                Clock.schedule_once(animate_legend_hide, 0.05)
            else:
                if self.map_legend in self.mapview.children:
                    self.mapview.remove_widget(self.map_legend)

        animate_legend_hide(0)
        print("Map Legend hidden")

    def go_to_start(self, instance):
        # Navigate back to the start screen
        self.parent.parent.current = 'start'

    def _update_rect(self, instance, value):
        # Update background rectangle on size/position change
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def show_map(self, instance):
        # Perform location anonymization in a separate thread
        self.submit_button.disabled = True
        self.submit_button.text = "Loading..."
        self.submit_button.background_color = (0.5, 0.5, 0.5, 1)

        # API calls in separate thread
        def api_thread():
            try:
                self._perform_api_calls()
            except Exception as e:
                print(f"❌ Error in API thread: {e}")
                traceback.print_exc()
                Clock.schedule_once(lambda dt: self.show_error_popup("API Error", str(e)))
            finally:
                # Reset Submit Button to normal
                Clock.schedule_once(lambda dt: self._reset_submit_button())

        # Start thread
        thread = Thread(target=api_thread)
        thread.daemon = True
        thread.start()

    def _reset_submit_button(self):
        # Reset submit button state after API call
        self.submit_button.disabled = False
        self.submit_button.text = "Submit"
        self.submit_button.background_color = (0.1, 0.7, 0.3, 1)

    def _perform_api_calls(self):
        # Geocode address, fetch nearby locations, and update map markers
        self.original_address = self.address_input.text
        address = self.address_input.text

        # SSL Setup
        ctx = ssl._create_unverified_context(cafile=certifi.where())
        geopy.geocoders.options.default_ssl_context = ctx
        loc = Nominatim(user_agent="DeLocatorApp", timeout=10)

        # Check saved locations
        saved_locations = load_saved_locations()
        for location in saved_locations:
            if location["original_address"] == address:
                print(f"Address already saved: {location['address']}")
                Clock.schedule_once(lambda dt: self._update_ui_with_saved_location(location, loc))
                return

        # Geocoding
        location = loc.geocode(address)
        if not location:
            Clock.schedule_once(lambda dt: self.show_error_popup(
                "Address Not Found",
                "No address found for your input.\nPlease try a different search term."
            ))
            return

        print(f"Address found: {location.address}")

        try:
            amenities_data = get_places_with_fallback(None, location, radius=500)  # api=None
        except Exception as e:
            error_message = str(e)
            Clock.schedule_once(lambda dt: self.show_error_popup(
                "API Error", f"Failed to fetch nearby locations.\nError: {error_message}"
            ))
            return

        if not amenities_data:
            Clock.schedule_once(lambda dt: self.show_error_popup(
                "No Locations Found",
                "No public places found near this address.\nPlease try a different location."
            ))
            return

        # Process results
        amenities = [(place_data['address'], place_data['coordinates'])
                     for place_data in amenities_data]

        if not amenities:
            Clock.schedule_once(lambda dt: self.show_error_popup(
                "No Valid Addresses",
                "No valid public place addresses found.\nPlease try a different location."
            ))
            return

        # Random selection
        selected_place, (lon, lat) = random.choice(amenities)

        # UI Update in Main Thread
        Clock.schedule_once(lambda dt: self._update_ui_with_new_location(
            selected_place, lat, lon, location
        ))

    def _update_ui_with_saved_location(self, saved_location, geocoder):
        # Update the map with saved location data
        try:
            self.address_input.text = saved_location["address"]

            original_address = geocoder.geocode(saved_location["original_address"])
            address = geocoder.geocode(saved_location['address'])

            self._update_map_markers(address.latitude, address.longitude,
                                     original_address.latitude, original_address.longitude)
        except Exception as e:
            print(f"Error updating saved location: {e}")
            pass

    def _update_ui_with_new_location(self, selected_place, lat, lon, original_location):
        # Update the map with new anonymized location data
        try:
            self.address_input.text = selected_place
            self._update_map_markers(lat, lon, original_location.latitude, original_location.longitude)
        except Exception as e:
            print(f"Error updating new location: {e}")
            pass

    def _update_map_markers(self, new_lat, new_lon, old_lat, old_lon):
        # Update marker positions on the map
        self.marker_new_address.lat = new_lat
        self.marker_new_address.lon = new_lon
        self.marker_old_address.lat = old_lat
        self.marker_old_address.lon = old_lon

        # Center map
        center_lat = (new_lat + old_lat) / 2
        center_lon = (new_lon + old_lon) / 2
        self.mapview.center_on(center_lat, center_lon)

        # Show map
        self.mapview.opacity = 1

        # Show legend
        Clock.schedule_once(lambda dt: self.show_legend(), 0.5)

    def show_error_popup(self, title, message):
        # Show a popup for error messages
        error_popup = Popup(
            title=title,
            title_color=(0, 0, 0, 1),
            content=Label(
                text=message,
                color=(0, 0, 0, 1),
                halign="center",
                valign="middle"
            ),
            size_hint=(0.8, 0.3),
            background="",
            background_color=(1, 1, 1, 1),
            auto_dismiss=True
        )
        error_popup.content.bind(size=error_popup.content.setter("text_size"))
        error_popup.open()

    def copy_text(self, instance):
        # Copy the address to clipboard and briefly change button color
        Clipboard.copy(self.address_input.text)
        instance.background_color = (0.5, 0.9, 0.5, 1)
        Clock.schedule_once(lambda dt: setattr(instance, 'background_color', (0.1, 0.7, 0.3, 1)), 0.2)

    def open_save_popup(self, instance):
        # Open the SavePopup for the current address
        address = self.address_input.text
        save_popup = SavePopup(original_address=self.original_address, address=address)
        save_popup.open()


# ShowSavedLocationsPopup: Popup window for viewing, copying, and deleting saved locations
class ShowSavedLocationsPopup(Popup):
    def __init__(self, saved_locations, **kwargs):
        super().__init__(**kwargs)
        self.title = "Saved Locations"
        self.size_hint = (0.9, 0.8)
        self.title_color = (0, 0, 0, 1)
        self.background = ""
        self.background_color = (1, 1, 1, 1)

        main_layout = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))

        # ScrollView for displaying all saved locations
        scroll_view = ScrollView()
        layout = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))

        for location in saved_locations:
            entry_layout = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(100), spacing=dp(5))

            address_layout = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(50))

            # Icon for the saved location
            icon_path = location.get("icon", None)
            if icon_path:
                icon = Image(source=icon_path, size_hint=(None, None), size=(dp(40), dp(40)))
                address_layout.add_widget(icon)

            # Address and description label
            address_label = Label(
                text=f"[b]{location['address']}[/b]\n{location.get('description', '')}",
                markup=True,
                size_hint_x=1,
                halign="left",
                valign="middle",
                color=(0, 0, 0, 1)
            )
            address_label.bind(size=address_label.setter("text_size"))
            address_layout.add_widget(address_label)

            entry_layout.add_widget(address_layout)

            # Copy and Delete buttons for each saved location
            button_layout = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))

            self.copy_button = Button(text='Copy', size_hint=(None, None), size=(dp(100), dp(40)),
                                      background_color=(0.1, 0.7, 0.3, 1), background_normal='', background_down='')
            self.copy_button.bind(on_release=lambda btn, address=location['address']: self.copy_address(address))
            button_layout.add_widget(self.copy_button)

            delete_button = Button(
                text="Delete",
                size_hint=(None, None),
                size=(dp(100), dp(40)),
                background_color=(0.9, 0.3, 0.3, 1),
                background_normal=""
            )
            delete_button.bind(on_release=lambda btn, address=location['address']: self.delete_address(address))
            button_layout.add_widget(delete_button)

            entry_layout.add_widget(button_layout)
            layout.add_widget(entry_layout)

        scroll_view.add_widget(layout)
        main_layout.add_widget(scroll_view)

        self.content = main_layout

    def copy_address(self, address):
        # Copy the address to the clipboard
        Clipboard.copy(address)

    def delete_address(self, address):
        # Delete the location from saved locations and update the popup
        saved_locations = load_saved_locations()
        saved_locations = [location for location in saved_locations if location['address'] != address]
        save_saved_locations(saved_locations)

        # Re-register broadcast receiver for Android notifications if needed
        if platform == "android":
            app = App.get_running_app()
            print(f"Re-registering BroadcastReceiver after Delete (now {len(saved_locations)} locations)...")

            if hasattr(app, 'copy_receiver') and app.copy_receiver is not None:
                try:
                    ctx = autoclass('org.kivy.android.PythonActivity').mActivity
                    java_receiver = app.copy_receiver.receiver
                    ctx.unregisterReceiver(java_receiver)
                    print("Old BroadcastReceiver unregistered")
                except Exception as e:
                    print(f"Error unregistering old receiver: {e}")

            app.register_broadcast_receiver()

        self.dismiss()
        ShowSavedLocationsPopup(saved_locations=saved_locations).open()


# StartScreen: The main/home screen of the app
class StartScreen(Screen):
    def __init__(self, **kwargs):
        super(StartScreen, self).__init__(**kwargs)

        # Set the window background color to white
        Window.clearcolor = (1, 1, 1, 1)
        main_layout = FloatLayout()

        # Create a vertically oriented layout for the main content
        center_layout = BoxLayout(
            orientation='vertical',
            padding=20,
            spacing=20,
            size_hint=(1, 1),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )

        # Spacer above logo
        center_layout.add_widget(BoxLayout(size_hint=(1, None), height=(Window.height - dp(200))))

        # Add the logo image to the layout
        logo = Image(source='icons/logo.png', size_hint=(None, None), size=(dp(300), dp(300)),
                     pos_hint={'center_x': 0.5})
        center_layout.add_widget(logo)

        # Add the grid of navigation buttons
        button_grid = self.create_buttons()
        center_layout.add_widget(button_grid)

        # Spacer below logo
        center_layout.add_widget(BoxLayout(size_hint=(1, None), height=(Window.height - logo.height) / 2))

        # Add circular info button (top-right corner)
        info_button = self.create_enhanced_info_button()

        # Add layouts/buttons to the main layout
        main_layout.add_widget(center_layout)
        main_layout.add_widget(info_button)

        self.add_widget(main_layout)

    def create_buttons(self):
        """
        Creates the main navigation buttons for generating new locations and viewing saved locations.
        """
        button_grid = GridLayout(cols=1, spacing=20, size_hint_y=None)

        generate_new_button = Button(text='Generate New', size_hint_y=None, height=dp(50),
                                     background_color=(0.3, 0.6, 0.9, 1), background_normal='', background_down='')
        generate_new_button.bind(on_release=self.generate_new)

        saved_locations_button = Button(text='Saved Locations', size_hint_y=None, height=dp(50),
                                        background_color=(0.3, 0.6, 0.9, 1), background_normal='', background_down='')
        saved_locations_button.bind(on_release=self.show_saved_locations)

        button_grid.add_widget(generate_new_button)
        button_grid.add_widget(saved_locations_button)

        return button_grid

    def create_enhanced_info_button(self):
        """
        Creates an enhanced circular info button for showing app information.
        Placed at the top right of the screen.
        """

        class CircularInfoButton(Button):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                # Update graphics on size/position change
                self.bind(pos=self.update_graphics, size=self.update_graphics)
                # Update position when window size changes
                Window.bind(size=self.update_position)
                Clock.schedule_once(self.update_position, 0.1)

            def update_position(self, *args):
                # Position button in top right corner
                self.pos = (Window.width - dp(60), Window.height - dp(60))
                self.update_graphics()

            def update_graphics(self, *args):
                # Draw outer and inner circles for circular effect
                self.canvas.before.clear()
                with self.canvas.before:
                    Color(0, 0, 0, 1)
                    d = min(self.width, self.height)
                    Ellipse(pos=(self.center_x - d / 2, self.center_y - d / 2), size=(d, d))
                    Color(1, 1, 1, 1)
                    border_width = dp(2)
                    inner_d = d - 2 * border_width
                    Ellipse(pos=(self.center_x - inner_d / 2, self.center_y - inner_d / 2),
                            size=(inner_d, inner_d))

        # Instantiate and style the info button
        info_button = CircularInfoButton(
            text='i',
            color=(0, 0, 0, 1),  # Blue text
            size_hint=(None, None),
            size=(dp(35), dp(35)),
            background_color=(0, 0, 0, 0),
            background_normal='',
            background_down='',
            font_size='24sp',
            bold=True
        )
        info_button.bind(on_release=self.show_info)
        return info_button

    def show_info(self, instance):
        """
        Displays the InfoPopup when the info button is pressed.
        """
        info_popup = InfoPopup()
        info_popup.open()

    def generate_new(self, instance):
        """
        Navigates to the map screen when 'Generate New' is pressed.
        """
        self.manager.current = 'map'

    def show_saved_locations(self, instance):
        """
        Displays the saved locations popup if locations exist, otherwise shows a message.
        """
        saved_locations = load_saved_locations()
        if saved_locations:
            saved_locations_popup = ShowSavedLocationsPopup(saved_locations=saved_locations)
            saved_locations_popup.open()
        else:
            no_saved_locations_popup = Popup(title='Saved Locations', title_color=(0, 0, 0, 1),
                                             content=Label(text="No saved locations found.", color=(0, 0, 0, 1)),
                                             size_hint=(0.8, 0.2), background="", background_color=(1, 1, 1, 1))
            no_saved_locations_popup.open()


# MapScreen: The screen displaying the map and location anonymization logic
class MapScreen(Screen):
    def __init__(self, **kwargs):
        super(MapScreen, self).__init__(**kwargs)
        # Add the MapWithMarker widget to display the map and controls
        self.map_view = MapWithMarker()
        self.add_widget(self.map_view)

    def go_to_start(self, instance):
        """
        Navigates back to the start screen.
        """
        self.manager.current = 'start'


# Main application class
class MyApp(App):
    def build(self):
        # Create the screen manager and add your main screens
        sm = ScreenManager()
        sm.add_widget(StartScreen(name='start'))
        sm.add_widget(MapScreen(name='map'))

        # Request notification permissions on Android devices
        if platform == 'android':
            try:
                request_permissions([Permission.POST_NOTIFICATIONS])
            except:
                print("Permission request failed")

        return sm

    def handle_broadcast(self, context, intent):
        """
        Handles broadcast intents from Android notifications.
        Copies received address to clipboard and logs details for debugging.
        """
        print(f"BroadcastReceiver called!")
        print(f"Intent Action: {intent.getAction()}")

        extras = intent.getExtras()
        if extras:
            print(f"Intent Extras found:")
            for key in extras.keySet():
                value = extras.get(key)
                print(f"'{key}' = '{value}' (Type: {type(value)})")
        else:
            print("No Intent Extras found!")

        # Extract address from intent
        address = intent.getStringExtra("address")
        print(f"Extracted address: '{address}'")

        # If address is valid, copy it to clipboard
        if address and address != "None":
            Clipboard.copy(str(address))
            print(f"Address copied from notification: {address}")
        else:
            print(f"No valid address received: {address}")

    def on_pause(self):
        """
        Called when the app goes into the background.
        On Android, triggers notification setup.
        """
        if platform == 'android':
            try:
                self.notification = AndroidNotification()
                self.send_notification()
            except:
                print("Notification failed")
        return True

    def send_notification(self):
        '''
        Sends an Android notification with saved location shortcuts (action buttons)
        Only works on Android; prints a message if used elsewhere.
        '''
        try:
            # Load all saved locations from local storage
            saved_locations = load_saved_locations()
            if not saved_locations:
                print("No saved locations found. No notification sent.")
                return

            # Prepare Android system objects for notification creation
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            NotificationManager = autoclass('android.app.NotificationManager')
            NotificationChannel = autoclass('android.app.NotificationChannel')
            NotificationCompat_Builder = autoclass('androidx.core.app.NotificationCompat$Builder')
            PendingIntent = autoclass('android.app.PendingIntent')
            Intent = autoclass('android.content.Intent')
            BuildVersion = autoclass('android.os.Build$VERSION')

            context = PythonActivity.mActivity
            notification_manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
            pkg = context.getPackageName()

            # Create notification channel if on Android 8+ (API 26+)
            channel_id = "saved_locations_channel"
            if BuildVersion.SDK_INT >= 26:
                if notification_manager.getNotificationChannel(channel_id) is None:
                    channel = NotificationChannel(
                        channel_id, "Saved Locations", NotificationManager.IMPORTANCE_DEFAULT
                    )
                    notification_manager.createNotificationChannel(channel)

            # Build the notification
            notification_builder = NotificationCompat_Builder(context, channel_id)
            notification_builder.setSmallIcon(context.getApplicationInfo().icon)
            notification_builder.setContentTitle("Saved Locations")
            notification_builder.setContentText("Tap a location to copy the address")
            notification_builder.setAutoCancel(True)

            # Mapping icons to human-readable names
            icon_mapping = {
                "icons/home.png": "Home",
                "icons/work.png": "Work",
                "icons/family.png": "Family"
            }

            # Create an action button for each saved location
            for index, location in enumerate(saved_locations):
                address = location["address"]
                icon_path = location.get("icon", "")
                icon_text = icon_mapping.get(icon_path, "Location")

                print(f"Creating notification button {index}: '{icon_text}' -> '{address}'")

                # Create intent for each action button
                intent = Intent()
                intent.setAction(f"{pkg}.copy_address_{index}")
                intent.setPackage(pkg)

                JavaString = autoclass('java.lang.String')
                address_java = JavaString(str(address))
                intent.putExtra("address", address_java)

                print(f"Intent Extra set: 'address' = '{address_java}'")

                request_code = 1000 + index

                # Use correct pending intent flags for Android version
                if BuildVersion.SDK_INT >= 31:
                    flag = PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT
                else:
                    flag = PendingIntent.FLAG_UPDATE_CURRENT

                pending_intent = PendingIntent.getBroadcast(context, request_code, intent, flag)

                # Add the action to the notification builder
                notification_builder.addAction(0, JavaString(icon_text), pending_intent)

            notification_manager.notify(1, notification_builder.build())
            print("Notification with saved locations sent.")

        # Send the notification to the system
        except Exception as e:
            print(f"Error sending notification: {e}")
            import traceback
            traceback.print_exc()

    def register_broadcast_receiver(self):
        """
        Registers the Android BroadcastReceiver to handle notification actions.
        Only registers if saved locations exist.
        """
        if platform != "android":
            return

        saved_locations = load_saved_locations()
        if not saved_locations:
            print("No saved_locations - BroadcastReceiver not registered")
            self.copy_receiver = None
            return

        try:
            # Android Java object imports
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            IntentFilter = autoclass('android.content.IntentFilter')
            BuildVersion = autoclass('android.os.Build$VERSION')

            ctx = PythonActivity.mActivity
            pkg = ctx.getPackageName()
            actions = [f"{pkg}.copy_address_{i}" for i in range(len(saved_locations))]

            filter = IntentFilter()
            for action in actions:
                filter.addAction(action)

            # Set up the BroadcastReceiver for each saved location
            self.copy_receiver = BroadcastReceiver(self.handle_broadcast, actions=actions)
            java_receiver = self.copy_receiver.receiver

            # Correct registration for Android 13+ (SDK 33+)
            if BuildVersion.SDK_INT >= 33:
                RECEIVER_EXPORTED = 2
                ctx.registerReceiver(java_receiver, filter, RECEIVER_EXPORTED)
            else:
                ctx.registerReceiver(java_receiver, filter)

            print(f"BroadcastReceiver registered with {len(actions)} actions")
        except Exception as e:
            print(f"Error registering BroadcastReceiver: {e}")
            self.copy_receiver = None

    def on_start(self):
        """
        Called when the app starts.
        Registers the BroadcastReceiver for notifications if on Android.
        """
        if platform == 'android':
            try:
                self.register_broadcast_receiver()
            except Exception as e:
                print(f"Error starting BroadcastReceiver: {e}")

    def on_stop(self):
        """
        Called when the app is stopped.
        Unregisters the BroadcastReceiver if it was registered.
        """
        if platform == "android" and hasattr(self, "copy_receiver") and self.copy_receiver is not None:
            try:
                ctx = autoclass('org.kivy.android.PythonActivity').mActivity
                java_receiver = self.copy_receiver.receiver
                ctx.unregisterReceiver(java_receiver)
                print("BroadcastReceiver unregistered")
            except Exception as e:
                print(f"Error unregistering BroadcastReceiver: {e}")


# Helper functions for loading and saving locations to JSON file
def load_saved_locations():
    try:
        with open("saved_locations.json", "r") as file:
            saved_locations = json.load(file)
    except FileNotFoundError:
        saved_locations = []
    return saved_locations


def save_saved_locations(saved_locations):
    with open("saved_locations.json", "w") as file:
        json.dump(saved_locations, file)


# Run the application
if __name__ == '__main__':
    MyApp().run()