import pandas as pd

# Create a list of sample field reports with Telangana locations
data = {
    'Report_ID': [301, 302, 303, 304],
    'Field_Notes': [
        "EMERGENCY: Severe urban flooding in Hyderabad - Gachibowli area. Multiple vehicles submerged near DLF building. Need drainage clearing and rescue teams. Urgency: 9. Location: Hyderabad - Gachibowli",
        "Heavy rains have caused a partial roof collapse of an old structure in Warangal - Hanamkonda. Need structural engineers and debris removal. Urgency: 7. Location: Warangal - Hanamkonda",
        "Food and medicine shortage reported at the relief camp in Karimnagar Center. Supporting 200 displaced people. Need immediate supplies. Urgency: 8. Location: Karimnagar Center",
        "Power lines down across the main road in Nizamabad North due to strong winds. High risk of electrocution. Area needs to be cordoned off. Urgency: 6. Location: Nizamabad North"
    ],
    'Reported_By': ['District Collector', 'Local NGO', 'Volunteer Team A', 'Citizen'],
    'Time': ['09:00 AM', '11:30 AM', '01:45 PM', '04:20 PM']
}

# Create a DataFrame
df = pd.DataFrame(data)

# Save to Excel
filename = 'sample_field_reports.xlsx'
df.to_excel(filename, index=False)

print(f"Successfully updated {filename} with Telangana locations!")
