import re

with open('/home/moshy/linuxcnc/dev/ThorCNC/thorcnc/thorcnc.ui', 'r') as f:
    content = f.read()

# We need to hide the widgets by adding <property name="visible"><bool>false</bool></property>
# to lbl_probe_param_edge_width and dsb_probe_edge_width

content = re.sub(
    r'(<widget class="QLabel" name="lbl_probe_param_edge_width">)',
    r'\1\n                   <property name="visible">\n                    <bool>false</bool>\n                   </property>',
    content
)

content = re.sub(
    r'(<widget class="QDoubleSpinBox" name="dsb_probe_edge_width">)',
    r'\1\n                   <property name="visible">\n                    <bool>false</bool>\n                   </property>',
    content
)

with open('/home/moshy/linuxcnc/dev/ThorCNC/thorcnc/thorcnc.ui', 'w') as f:
    f.write(content)
