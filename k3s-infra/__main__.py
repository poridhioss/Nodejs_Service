import pulumi
import pulumi_aws as aws

# Configuration
config = pulumi.Config()
vpc_cidr = config.get("vpc_cidr") or "10.0.0.0/16"
public_subnet_cidr = config.get("public_subnet_cidr") or "10.0.1.0/24"
availability_zone = config.get("availability_zone") or "ap-southeast-1a"
ubuntu_ami_id = config.get("ami_id") or "ami-060e277c0d4cce553"  # Ubuntu 24.04 LTS
k3s_token = config.get("k3s_token") or "super-secret-token"

# Create a VPC
vpc = aws.ec2.Vpc("my-vpc",
    cidr_block=vpc_cidr,
    tags={
        "Name": "my-vpc"
    }
)

# Create a public subnet
public_subnet = aws.ec2.Subnet("public-subnet",
    vpc_id=vpc.id,
    cidr_block=public_subnet_cidr,
    availability_zone=availability_zone,
    map_public_ip_on_launch=True,
    tags={
        "Name": "public-subnet"
    }
)

# Create an Internet Gateway
igw = aws.ec2.InternetGateway("internet-gateway",
    vpc_id=vpc.id,
    tags={
        "Name": "igw"
    }
)

# Create a route table
public_route_table = aws.ec2.RouteTable("public-route-table",
    vpc_id=vpc.id,
    tags={
        "Name": "rt-public"
    }
)

# Create a route in the route table for the Internet Gateway
route = aws.ec2.Route("igw-route",
    route_table_id=public_route_table.id,
    destination_cidr_block="0.0.0.0/0",
    gateway_id=igw.id
)

# Associate the route table with the public subnet
route_table_association = aws.ec2.RouteTableAssociation("public-route-table-association",
    subnet_id=public_subnet.id,
    route_table_id=public_route_table.id
)

# Security Group for Load Balancer (nginx)
lb_security_group = aws.ec2.SecurityGroup("lb-secgrp",
    vpc_id=vpc.id,
    description="Security group for nginx load balancer",
    ingress=[
        # HTTP
        {
            "protocol": "tcp",
            "from_port": 80,
            "to_port": 80,
            "cidr_blocks": ["0.0.0.0/0"]
        },
        # HTTPS
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr_blocks": ["0.0.0.0/0"]
        },
        # SSH for administration
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"]
        }
    ],
    egress=[
        # Allow all outbound traffic to K3s nodes
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": ["0.0.0.0/0"]
        }
    ],
    tags={
        "Name": "nginx-lb-sg"
    }
)

# Security Group for K3s Cluster Nodes
k3s_security_group = aws.ec2.SecurityGroup("k3s-secgrp",
    vpc_id=vpc.id,
    description="Security group for K3s cluster nodes",
    ingress=[
        # K3s API server
        {
            "protocol": "tcp",
            "from_port": 6443,
            "to_port": 6443,
            "cidr_blocks": [public_subnet.cidr_block]
        },
        # Flannel VXLAN
        {
            "protocol": "udp",
            "from_port": 8472,
            "to_port": 8472,
            "cidr_blocks": [public_subnet.cidr_block]
        },
        # SSH for administration
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"]
        },
        # HTTP/HTTPS for applications
        {
            "protocol": "tcp",
            "from_port": 80,
            "to_port": 80,
            "cidr_blocks": [public_subnet.cidr_block]
        },
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr_blocks": [public_subnet.cidr_block]
        },
        # Allow all internal cluster communication
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": [public_subnet.cidr_block]
        }
    ],
    egress=[
        # Allow all outbound traffic
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": ["0.0.0.0/0"]
        }
    ],
    tags={
        "Name": "k3s-cluster-sg"
    }
)

# User data for nginx load balancer
nginx_user_data = """#!/bin/bash
apt-get update
apt-get install -y nginx

# Configure nginx as load balancer for K3s API server
cat > /etc/nginx/nginx.conf << 'EOF'
events {}
stream {
    upstream k3s_servers {
        server MASTER_PRIVATE_IP:6443;
        server WORKER1_PRIVATE_IP:6443;
        server WORKER2_PRIVATE_IP:6443;
    }
    server {
        listen 6443;
        proxy_pass k3s_servers;
    }
}
EOF

systemctl enable nginx
systemctl restart nginx
"""

# Create K3s master instance
master_instance = aws.ec2.Instance("master-instance",
    instance_type="t3.small",
    vpc_security_group_ids=[k3s_security_group.id],
    ami=ubuntu_ami_id,
    subnet_id=public_subnet.id,
    key_name="k3sCluster",
    associate_public_ip_address=True,
    user_data=f"""#!/bin/bash
# Install K3s server
curl -sfL https://get.k3s.io | K3S_TOKEN="{k3s_token}" sh -s - server \\
  --cluster-init

# Wait for K3s to be ready
until kubectl get nodes 2>/dev/null; do
    echo "Waiting for K3s to start..."
    sleep 5
done

# Get kubeconfig for external access
cp /etc/rancher/k3s/k3s.yaml /home/ubuntu/k3s.yaml
chown ubuntu:ubuntu /home/ubuntu/k3s.yaml
""",
    tags={
        "Name": "k3s-master"
    }
)

# User data for K3s worker nodes
worker_user_data = pulumi.Output.all(master_instance.private_ip).apply(
    lambda ips: f"""#!/bin/bash
# Install K3s agent
curl -sfL https://get.k3s.io | K3S_TOKEN="{k3s_token}" K3S_URL=https://{ips[0]}:6443 sh -s -
"""
)

# Create K3s worker instances
worker1_instance = aws.ec2.Instance("worker1-instance",
    instance_type="t3.small",
    vpc_security_group_ids=[k3s_security_group.id],
    ami=ubuntu_ami_id,
    subnet_id=public_subnet.id,
    key_name="k3sCluster",
    associate_public_ip_address=True,
    user_data=worker_user_data,
    tags={
        "Name": "k3s-worker1"
    }
)

worker2_instance = aws.ec2.Instance("worker2-instance",
    instance_type="t3.small",
    vpc_security_group_ids=[k3s_security_group.id],
    ami=ubuntu_ami_id,
    subnet_id=public_subnet.id,
    key_name="k3sCluster",
    associate_public_ip_address=True,
    user_data=worker_user_data,
    tags={
        "Name": "k3s-worker2"
    }
)

# Create nginx load balancer instance (after worker instances so we can get their IPs)
nginx_user_data_final = pulumi.Output.all(
    master_instance.private_ip, 
    worker1_instance.private_ip, 
    worker2_instance.private_ip
).apply(lambda ips: nginx_user_data
    .replace("MASTER_PRIVATE_IP", ips[0])
    .replace("WORKER1_PRIVATE_IP", ips[1])
    .replace("WORKER2_PRIVATE_IP", ips[2])
)

nginx_instance = aws.ec2.Instance("nginx-instance",
    instance_type="t2.micro",
    vpc_security_group_ids=[lb_security_group.id],
    ami=ubuntu_ami_id,
    subnet_id=public_subnet.id,
    key_name="nginx",
    associate_public_ip_address=True,
    user_data=nginx_user_data_final,
    tags={
        "Name": "nginx-lb"
    }
)

# Export outputs
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnet_id", public_subnet.id)
pulumi.export("igw_id", igw.id)
pulumi.export("public_route_table_id", public_route_table.id)

pulumi.export("nginx_instance_id", nginx_instance.id)
pulumi.export("nginx_instance_ip", nginx_instance.public_ip)
pulumi.export("nginx_private_ip", nginx_instance.private_ip)

pulumi.export("master_instance_id", master_instance.id)
pulumi.export("master_instance_ip", master_instance.public_ip)
pulumi.export("master_private_ip", master_instance.private_ip)

pulumi.export("worker1_instance_id", worker1_instance.id)
pulumi.export("worker1_instance_ip", worker1_instance.public_ip)
pulumi.export("worker1_private_ip", worker1_instance.private_ip)

pulumi.export("worker2_instance_id", worker2_instance.id)
pulumi.export("worker2_instance_ip", worker2_instance.public_ip)
pulumi.export("worker2_private_ip", worker2_instance.private_ip)