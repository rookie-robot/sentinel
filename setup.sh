
echo "create service files"
python3 create_services.py

echo "copy service files to /lib/systemd/system"
service_dir=./service/
sudo cp "$service_dir"/* /lib/systemd/system/
sudo systemctl daemon-reload

echo "enable services"
cd service_dir
for entry in ./
do
  echo "$entry"
#   sudo systemctl enable "$entry"
#   sudo systemctl start "$entry"
done

