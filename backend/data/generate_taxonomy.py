"""
data/generate_taxonomy.py
--------------------------
Authoritative source for the skill taxonomy.

RULES ENFORCED:
  R1. One alias -> one canonical only. Hard enforced at generation time.
  R2. Abstract concepts (Infrastructure as Code, Serverless, etc.) do NOT
      own tool-specific aliases. Tools do NOT own concept-level aliases.
  R3. Short ambiguous aliases (tf, eda, dl, cv) are excluded unless
      there is one clear dominant meaning in tech job descriptions.
  R4. Vendor-vs-opensource duplicates are merged into one canonical using
      the most common hiring-market form.
  R5. Parent/child separation: parent never claims child's name as alias.
  R6. All aliases are lowercase and stripped before writing.

Run with:
    cd backend/
    python data/generate_taxonomy.py

Outputs:  data/skill_keywords.json
"""

import json
from pathlib import Path
from collections import defaultdict

OUTPUT = Path(__file__).parent / "skill_keywords.json"

# ─────────────────────────────────────────────────────────────────────────────
# TAXONOMY DEFINITION
# Each entry: (canonical, [aliases], category)
# Category: "Technical" | "Tool" | "Soft Skill" | "Certification"
# ─────────────────────────────────────────────────────────────────────────────

RAW = [

    # ═══════════════════════════════════════════════════════════════
    # PROGRAMMING LANGUAGES
    # ═══════════════════════════════════════════════════════════════

    ("Python",          ["python", "python3", "python 3", "py", "python2"], "Technical"),
    ("JavaScript",      ["javascript", "js", "ecmascript", "es6", "es2015", "es2020", "vanilla js"], "Technical"),
    ("TypeScript",      ["typescript", "ts", "type script"], "Technical"),
    ("Java",            ["java", "java 8", "java 11", "java 17", "java se", "java ee", "core java"], "Technical"),
    ("Go",              ["golang", "go lang", "go programming"], "Technical"),
    # NOTE: "go" excluded — too ambiguous (English word). "golang" is unambiguous.

    ("Rust",            ["rust", "rustlang", "rust lang", "rust programming"], "Technical"),
    ("C++",             ["c++", "cpp", "c plus plus"], "Technical"),
    ("C#",              ["c#", "csharp", "c sharp"], "Technical"),
    ("C",               ["c programming", "c language", "ansi c", "c99", "c11"], "Technical"),
    # NOTE: single-char alias "c" excluded — extreme false positive risk.

    ("R",               ["r programming", "r language", "rstats", "r statistical computing"], "Technical"),
    # NOTE: single-char alias "r" excluded — extreme false positive risk.

    ("Scala",           ["scala", "scala lang"], "Technical"),
    ("PHP",             ["php", "php7", "php8", "php 7", "php 8"], "Technical"),
    ("Ruby",            ["ruby", "rails", "ror"], "Technical"),
    ("Swift",           ["swift", "swift 5", "swift programming"], "Technical"),
    # NOTE: "swiftui" belongs to iOS Development, not Swift language.

    ("Kotlin",          ["kotlin", "kotlin android", "kotlin jvm"], "Technical"),
    ("Dart",            ["dart", "dart lang"], "Technical"),
    ("MATLAB",          ["matlab", "mat lab"], "Technical"),
    ("Julia",           ["julia", "julialang", "julia lang"], "Technical"),
    ("Perl",            ["perl", "perl 5"], "Technical"),
    ("Groovy",          ["groovy", "groovy scripting", "groovy jvm"], "Technical"),
    ("Elixir",          ["elixir", "elixir lang", "phoenix framework", "elixir phoenix"], "Technical"),
    ("Haskell",         ["haskell", "haskell functional"], "Technical"),
    ("Lua",             ["lua", "lua scripting"], "Technical"),
    ("Assembly",        ["assembly", "asm", "assembly language", "x86 assembly"], "Technical"),
    ("Shell Scripting", ["bash", "shell scripting", "shell script", "bash scripting", "zsh", "unix shell", "linux shell"], "Technical"),
    ("PowerShell",      ["powershell", "windows powershell", "ps scripting"], "Technical"),
    ("WebAssembly",     ["webassembly", "wasm", "web assembly"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # DATABASES — RELATIONAL
    # ═══════════════════════════════════════════════════════════════

    ("SQL",                  ["sql", "structured query language", "ansi sql", "pl/sql", "plsql", "pl sql", "t-sql", "transact-sql"], "Technical"),
    ("PostgreSQL",           ["postgresql", "postgres", "pgsql", "pg"], "Technical"),
    ("MySQL",                ["mysql", "my sql"], "Technical"),
    ("SQLite",               ["sqlite", "sqlite3"], "Technical"),
    ("Microsoft SQL Server", ["microsoft sql server", "mssql", "ms sql", "sql server"], "Technical"),
    ("Oracle Database",      ["oracle", "oracle db", "oracle database", "oracle sql", "oracle 19c", "oracle 12c"], "Technical"),
    ("MariaDB",              ["mariadb", "maria db"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # DATABASES — NoSQL / CLOUD
    # ═══════════════════════════════════════════════════════════════

    # R4: Merged "Cassandra" + "Apache Cassandra" into one canonical.
    ("Cassandra",  ["cassandra", "apache cassandra", "cql", "datastax cassandra"], "Technical"),

    ("MongoDB",    ["mongodb", "mongo", "mongo db"], "Technical"),
    ("Redis",      ["redis", "redis cache", "redis cluster"], "Technical"),
    # R5: "opensearch" belongs to OpenSearch, not Elasticsearch.
    ("Elasticsearch", ["elasticsearch", "elastic search", "elk stack", "elastic stack"], "Technical"),
    ("OpenSearch",    ["opensearch", "amazon opensearch", "open search"], "Technical"),
    ("DynamoDB",      ["dynamodb", "dynamo db", "aws dynamodb"], "Technical"),
    ("BigQuery",      ["bigquery", "big query", "google bigquery", "bq"], "Technical"),
    # NOTE: "GCP BigQuery" removed as separate canonical (R2/R4 — product vs ecosystem dup).

    ("Snowflake",  ["snowflake", "snowflake data warehouse", "snowflake cloud"], "Technical"),
    ("Redshift",   ["redshift", "aws redshift", "amazon redshift"], "Technical"),

    # R4: "Neo4j" is the canonical name. "graph database" is a concept — given to Neo4j since it dominates.
    ("Neo4j",      ["neo4j", "neo4j graph", "graph database", "cypher query", "cypher"], "Technical"),

    ("InfluxDB",       ["influxdb", "influx db", "influxdb time series"], "Technical"),
    ("CockroachDB",    ["cockroachdb", "cockroach db"], "Technical"),
    ("Pinecone",       ["pinecone", "pinecone vector db"], "Technical"),
    ("Weaviate",       ["weaviate", "weaviate vector"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # FRONTEND FRAMEWORKS & LIBRARIES
    # ═══════════════════════════════════════════════════════════════

    # R5: "react native" removed from React — belongs to React Native.
    ("React",       ["react", "reactjs", "react.js", "react js", "react hooks", "react 18", "jsx"], "Technical"),
    ("React Native",["react native", "react-native", "rn"], "Technical"),
    ("Angular",     ["angular", "angularjs", "angular.js", "angular 14", "angular 15", "angular 16", "angular 17"], "Technical"),
    ("Vue.js",      ["vue", "vuejs", "vue.js", "vue 3", "vue 2"], "Technical"),
    ("Nuxt.js",     ["nuxt", "nuxt.js", "nuxtjs", "nuxt 3"], "Technical"),
    ("Next.js",     ["next.js", "nextjs", "next js", "next 13", "next 14"], "Technical"),
    ("Svelte",      ["svelte", "sveltekit", "svelte kit"], "Technical"),
    ("jQuery",      ["jquery", "jquery ui"], "Technical"),
    ("HTML",        ["html", "html5", "html 5"], "Technical"),
    ("CSS",         ["css", "css3", "sass", "scss", "less"], "Technical"),
    ("Tailwind CSS",["tailwind", "tailwindcss", "tailwind css"], "Technical"),
    ("Bootstrap",   ["bootstrap", "bootstrap 4", "bootstrap 5"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # BACKEND FRAMEWORKS
    # ═══════════════════════════════════════════════════════════════

    ("Node.js",     ["node.js", "nodejs", "node js"], "Technical"),
    # NOTE: bare "node" excluded — ambiguous with graph theory "node".

    ("Express.js",  ["express", "expressjs", "express.js", "express js"], "Technical"),
    ("FastAPI",     ["fastapi", "fast api"], "Technical"),
    ("Django",      ["django", "django rest framework", "django orm", "drf"], "Technical"),
    ("Flask",       ["flask", "flask api", "flask python"], "Technical"),
    ("Spring Boot", ["spring boot", "springboot", "spring framework", "spring mvc", "spring cloud", "spring security"], "Technical"),
    ("Laravel",     ["laravel", "laravel php"], "Technical"),
    ("ASP.NET",     ["asp.net", "aspnet", ".net core", "dotnet core", ".net 6", ".net 7", ".net 8"], "Technical"),
    ("Nest.js",     ["nestjs", "nest.js", "nest js"], "Technical"),
    ("Ruby on Rails", ["ruby on rails", "ror framework"], "Technical"),
    # NOTE: "rails" and "ror" already in Ruby canonical.

    # ═══════════════════════════════════════════════════════════════
    # API PARADIGMS
    # ═══════════════════════════════════════════════════════════════

    ("GraphQL",    ["graphql", "graph ql", "apollo graphql", "apollo server"], "Technical"),
    ("REST API",   ["rest api", "restful api", "restful services", "http api", "rest services"], "Technical"),
    # NOTE: bare "rest" excluded — collision risk with English word.

    # R2/R4: "protocol buffers" and "protobuf" belong to Protobuf, NOT gRPC.
    ("gRPC",       ["grpc", "g-rpc", "grpc framework", "grpc services"], "Technical"),
    ("Protobuf",   ["protobuf", "protocol buffers", "proto files", "proto format"], "Technical"),
    ("WebSocket",  ["websocket", "web socket", "socket.io", "socketio"], "Technical"),
    ("WebRTC",     ["webrtc", "web rtc", "real time communication", "peer to peer video"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # CLOUD — AWS CORE
    # ═══════════════════════════════════════════════════════════════

    ("AWS",                ["aws", "amazon web services", "amazon cloud"], "Technical"),
    ("AWS Lambda",         ["lambda", "aws lambda", "amazon lambda"], "Technical"),
    # NOTE: "faas", "serverless functions" → Serverless concept canonical, NOT Lambda.

    ("AWS S3",             ["s3", "aws s3", "amazon s3", "s3 bucket"], "Technical"),
    ("AWS EC2",            ["ec2", "aws ec2", "amazon ec2"], "Technical"),
    ("AWS ECS",            ["ecs", "aws ecs", "elastic container service"], "Technical"),
    ("AWS EKS",            ["eks", "aws eks", "elastic kubernetes service", "kubernetes on aws"], "Technical"),
    ("AWS RDS",            ["rds", "aws rds", "relational database service"], "Technical"),
    ("AWS SQS",            ["sqs", "aws sqs", "simple queue service"], "Technical"),
    ("AWS SNS",            ["sns", "aws sns", "simple notification service"], "Technical"),
    ("AWS CloudFormation", ["cloudformation", "aws cloudformation", "cfn"], "Technical"),
    ("AWS CDK",            ["aws cdk", "cloud development kit"], "Technical"),
    # NOTE: bare "cdk" excluded — too short.

    ("AWS Glue",           ["aws glue", "glue etl", "glue catalog"], "Technical"),
    ("AWS Athena",         ["athena", "aws athena"], "Technical"),
    ("AWS EMR",            ["emr", "aws emr", "elastic mapreduce"], "Technical"),
    ("AWS Kinesis",        ["kinesis", "aws kinesis", "amazon kinesis", "kinesis data streams", "kinesis firehose"], "Technical"),
    # NOTE: "Firehose" standalone canonical removed — merged here (R4).

    ("AWS Step Functions", ["step functions", "aws step functions", "state machines"], "Technical"),
    ("AWS EventBridge",    ["eventbridge", "aws eventbridge", "event bridge"], "Technical"),
    ("AWS Sagemaker",      ["sagemaker", "aws sagemaker", "amazon sagemaker"], "Technical"),
    ("AWS IAM",            ["aws iam", "identity and access management", "iam policies", "iam roles"], "Technical"),
    # NOTE: bare "iam" excluded — ambiguous (IAM = Identity & Access, but also a common verb pattern).

    ("CloudWatch",         ["cloudwatch", "aws cloudwatch", "cloud watch"], "Tool"),

    # ═══════════════════════════════════════════════════════════════
    # CLOUD — GCP
    # ═══════════════════════════════════════════════════════════════

    ("GCP",               ["gcp", "google cloud", "google cloud platform"], "Technical"),
    # NOTE: GCP does NOT own gcp service aliases (BigQuery, Pub/Sub, etc. are independent).

    ("GCP Pub/Sub",       ["pubsub", "google pub/sub", "gcp pubsub", "cloud pubsub"], "Technical"),
    ("GCP Dataflow",      ["dataflow", "gcp dataflow", "google dataflow", "beam on gcp"], "Technical"),
    ("GCP Vertex AI",     ["vertex ai", "gcp vertex ai", "google vertex ai", "vertex"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # CLOUD — AZURE
    # ═══════════════════════════════════════════════════════════════

    ("Azure",              ["azure", "microsoft azure", "azure cloud", "ms azure"], "Technical"),
    ("Azure DevOps",       ["azure devops", "azure pipelines", "vsts", "tfs"], "Technical"),
    # NOTE: "ado" excluded — collides with common abbreviation.

    ("Azure Data Factory", ["azure data factory", "adf"], "Technical"),
    ("Azure Synapse",      ["azure synapse", "synapse analytics"], "Technical"),
    ("Azure Functions",    ["azure functions", "azure serverless"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # CONTAINERISATION & ORCHESTRATION
    # ═══════════════════════════════════════════════════════════════

    ("Docker",      ["docker", "dockerfile", "docker-compose", "docker compose", "containerization", "docker container"], "Technical"),
    ("Kubernetes",  ["kubernetes", "k8s", "kubectl", "k8", "kube"], "Technical"),
    ("Helm",        ["helm", "helm chart", "helm charts", "kubernetes helm"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # INFRASTRUCTURE & IaC TOOLS
    # ═══════════════════════════════════════════════════════════════

    # R2: Terraform does NOT own concept aliases (iac, infrastructure as code).
    # Those belong to the Infrastructure as Code concept canonical.
    ("Terraform",   ["terraform", "hashicorp terraform", "terraform cloud"], "Technical"),
    ("Ansible",     ["ansible", "ansible playbook", "ansible automation"], "Technical"),
    ("Pulumi",      ["pulumi", "pulumi iac", "pulumi cloud"], "Technical"),

    # R1: Infrastructure as Code is a CONCEPT — owns "iac", "infrastructure as code".
    # Tools (Terraform, Pulumi, Ansible) do NOT claim these aliases.
    ("Infrastructure as Code", ["infrastructure as code", "iac", "programmable infrastructure"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # DATA ENGINEERING — PROCESSING
    # ═══════════════════════════════════════════════════════════════

    # R5: Apache Spark does NOT own "databricks spark" — that belongs to Databricks.
    ("Apache Spark",   ["spark", "apache spark", "pyspark", "spark sql", "spark streaming", "spark ml"], "Technical"),

    # R5: Apache Kafka does NOT own "kafka connect" — that belongs to Kafka Connect.
    ("Apache Kafka",   ["kafka", "apache kafka", "kafka streams", "confluent kafka"], "Technical"),
    ("Kafka Connect",  ["kafka connect", "kafka connector", "kafka sink connector", "kafka source connector"], "Technical"),

    ("Apache Airflow", ["airflow", "apache airflow", "airflow dag", "airflow pipeline"], "Technical"),
    ("Apache Hadoop",  ["hadoop", "apache hadoop", "hdfs", "hadoop distributed file system", "mapreduce", "yarn hadoop"], "Technical"),
    ("Apache Hive",    ["hive", "apache hive", "hiveql", "hql"], "Technical"),
    ("Apache Flink",   ["flink", "apache flink", "flink streaming", "flink sql"], "Technical"),
    ("Apache Beam",    ["apache beam", "beam pipeline", "beam sdk"], "Technical"),
    ("Apache NiFi",    ["nifi", "apache nifi"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # DATA ENGINEERING — PLATFORMS & FORMATS
    # ═══════════════════════════════════════════════════════════════

    # R5: Databricks does NOT own "databricks spark" (belongs to Spark) or "delta lake" (its own canonical).
    ("Databricks",    ["databricks", "databricks notebooks", "databricks lakehouse", "databricks platform"], "Technical"),

    # R3: Delta Lake is a CHILD of Databricks ecosystem but owns its own aliases.
    # Data Lake (concept) does NOT claim "delta lake".
    ("Delta Lake",    ["delta lake", "delta table", "databricks delta", "delta format"], "Technical"),

    ("dbt",           ["dbt", "data build tool", "dbt core"], "Technical"),
    # R5: dbt does NOT own "dbt cloud" — belongs to dbt Cloud.
    ("dbt Cloud",     ["dbt cloud", "dbt cloud ide"], "Tool"),

    ("Dagster",       ["dagster", "dagster io", "dagster pipeline"], "Technical"),
    ("Prefect",       ["prefect", "prefect cloud", "prefect core", "prefect 2"], "Technical"),
    ("Luigi",         ["luigi", "spotify luigi", "luigi pipeline"], "Technical"),
    ("dask",          ["dask", "dask dataframe", "dask distributed"], "Technical"),

    # Data formats
    ("Apache Parquet", ["parquet", "apache parquet", "parquet format"], "Technical"),
    ("Apache Avro",    ["avro", "apache avro", "avro schema", "avro format"], "Technical"),
    ("Apache ORC",     ["orc", "apache orc", "orc format"], "Technical"),
    ("Apache Iceberg", ["iceberg", "apache iceberg", "iceberg table format"], "Technical"),
    ("Apache Hudi",    ["hudi", "apache hudi"], "Technical"),

    # Query engines
    ("Apache Druid",  ["druid", "apache druid", "druid real-time analytics"], "Technical"),
    ("ClickHouse",    ["clickhouse", "click house", "yandex clickhouse"], "Technical"),
    # R4: Trino + Presto merged — Presto is parent, Trino is the open-source fork.
    # Using Presto as canonical with Trino as alias since both appear in job posts.
    ("Presto / Trino", ["presto", "prestodb", "trino", "trinodb", "trino sql", "starburst"], "Technical"),
    ("Apache Pulsar",  ["pulsar", "apache pulsar", "pulsar messaging"], "Technical"),
    ("NATS",           ["nats", "nats.io", "nats messaging"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # ML / AI — CONCEPTS (ABSTRACT, DO NOT OWN TOOL ALIASES)
    # ═══════════════════════════════════════════════════════════════

    ("Machine Learning",      ["machine learning", "ml", "supervised learning", "unsupervised learning", "applied ml", "predictive modeling", "classical ml"], "Technical"),
    # NOTE: "ml" included here — clearly dominant (Machine Learning). No other canonical claims it.

    ("Deep Learning",         ["deep learning", "neural networks", "neural network", "deep neural network", "dnn"], "Technical"),
    # NOTE: "dl" excluded — ambiguous (Data Lake, Docker Layer in other contexts).

    ("NLP",                   ["nlp", "natural language processing", "text mining", "text analytics", "computational linguistics"], "Technical"),
    ("Computer Vision",       ["computer vision", "image recognition", "object detection", "image segmentation"], "Technical"),
    # NOTE: "cv" excluded — extreme false positive risk (curriculum vitae, cover letter).

    ("Generative AI",         ["generative ai", "gen ai", "genai", "large language models", "foundation models", "ai generation"], "Technical"),
    # NOTE: "llm"/"llms" excluded here — see LLMs canonical below for specificity.

    ("LLMs",                  ["llm", "llms", "large language model", "llm development", "llm fine-tuning"], "Technical"),
    ("Reinforcement Learning", ["reinforcement learning", "deep reinforcement learning", "drl", "rl agent"], "Technical"),
    # NOTE: "rl" excluded — ambiguous.

    ("MLOps",                 ["mlops", "ml ops", "machine learning operations", "model deployment", "model serving", "model monitoring"], "Technical"),
    ("Feature Engineering",   ["feature engineering", "feature selection", "feature extraction", "feature store"], "Technical"),
    ("RAG",                   ["rag", "retrieval augmented generation", "retrieval-augmented generation"], "Technical"),
    ("Prompt Engineering",    ["prompt engineering", "prompt design", "few-shot prompting", "chain of thought prompting"], "Technical"),
    ("Vector Embeddings",     ["embeddings", "vector embeddings", "semantic embeddings", "text embeddings", "word embeddings"], "Technical"),
    ("Anomaly Detection",     ["anomaly detection", "outlier detection", "fraud detection ml"], "Technical"),
    ("Time Series Analysis",  ["time series", "time series analysis", "time series forecasting", "arima", "lstm forecasting"], "Technical"),
    ("Recommendation Systems",["recommendation system", "recommender system", "collaborative filtering", "content based filtering"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # ML / AI — FRAMEWORKS & TOOLS
    # ═══════════════════════════════════════════════════════════════

    # NOTE: "tf" removed — ambiguous (TensorFlow vs Terraform, cross-layer).
    ("TensorFlow",    ["tensorflow", "tensorflow 2", "tensorflow keras"], "Technical"),
    ("PyTorch",       ["pytorch", "torch", "py torch"], "Technical"),
    ("Keras",         ["keras", "keras api", "keras tensorflow"], "Technical"),
    ("Scikit-learn",  ["scikit-learn", "sklearn", "scikit learn", "scikitlearn"], "Technical"),
    ("XGBoost",       ["xgboost", "xgb", "gradient boosting", "extreme gradient boosting"], "Technical"),
    ("LightGBM",      ["lightgbm", "lgbm", "light gbm"], "Technical"),
    ("CatBoost",      ["catboost", "cat boost"], "Technical"),
    ("Hugging Face",  ["hugging face", "huggingface", "transformers library", "hf transformers"], "Technical"),
    ("LangChain",     ["langchain", "lang chain"], "Technical"),
    ("LlamaIndex",    ["llamaindex", "llama index", "llama hub"], "Technical"),
    ("OpenAI API",    ["openai", "openai api", "chatgpt api", "gpt-4", "gpt-3", "gpt4", "openai gpt"], "Technical"),
    ("Ollama",        ["ollama", "ollama local llm"], "Technical"),
    ("FAISS",         ["faiss", "facebook ai similarity search"], "Technical"),
    ("Milvus",        ["milvus", "milvus vector db"], "Technical"),
    ("Kubeflow",      ["kubeflow", "kubeflow pipeline", "kfp"], "Technical"),

    # ML Data/Python stack
    ("Pandas",         ["pandas", "pandas dataframe", "pandas library"], "Technical"),
    ("NumPy",          ["numpy", "numpy array"], "Technical"),
    # NOTE: "np" excluded — too short.

    ("Matplotlib",     ["matplotlib", "matplotlib pyplot", "pyplot"], "Technical"),
    ("Seaborn",        ["seaborn", "seaborn plots"], "Technical"),
    ("Plotly",         ["plotly", "plotly dash", "dash framework"], "Technical"),
    ("SciPy",          ["scipy", "scipy stats", "scientific python"], "Technical"),
    ("OpenCV",         ["opencv", "open cv", "cv2"], "Technical"),
    ("NLTK",           ["nltk", "natural language toolkit"], "Technical"),
    ("spaCy",          ["spacy", "spacy nlp", "spacy pipeline"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # ARCHITECTURE CONCEPTS (ABSTRACT)
    # ═══════════════════════════════════════════════════════════════

    # R1: Concept canonicals own their concept aliases ONLY.
    # "Serverless" does NOT own aws lambda, faas (product aliases).
    ("Serverless",          ["serverless", "serverless architecture", "serverless computing", "faas", "function as a service"], "Technical"),
    # NOTE: "faas" given to Serverless concept as it's more architecture than a specific service.

    # R3: Event-Driven Architecture drops "eda" — collides with Exploratory Data Analysis.
    ("Event-Driven Architecture", ["event-driven architecture", "event driven design", "event sourcing", "event streaming architecture", "cqrs"], "Technical"),

    ("Microservices",       ["microservices", "micro services", "microservice architecture", "service oriented architecture"], "Technical"),
    ("Distributed Systems", ["distributed systems", "distributed computing", "distributed architecture"], "Technical"),
    ("System Design",       ["system design", "solution architecture", "high level design", "hld", "low level design", "lld"], "Technical"),
    ("API Design",          ["api design", "api architecture", "api gateway", "api management"], "Technical"),
    ("Data Modeling",       ["data modeling", "data modelling", "dimensional modeling", "star schema", "snowflake schema", "er diagram"], "Technical"),
    ("Data Warehousing",    ["data warehouse", "data warehousing", "dwh", "edw", "enterprise data warehouse", "data mart"], "Technical"),
    ("Data Lake",           ["data lake", "datalake", "data lakehouse", "lakehouse architecture"], "Technical"),
    # NOTE: "delta lake" removed from Data Lake — belongs to Delta Lake canonical (R3).

    ("ETL",                 ["etl", "elt", "extract transform load", "data pipeline", "data pipelines", "data ingestion", "data integration"], "Technical"),
    ("Data Engineering",    ["data engineering", "big data engineering"], "Technical"),
    # NOTE: "data engineer" removed — it's a job title, not a skill alias.

    ("Data Science",        ["data science", "applied data science", "predictive analytics"], "Technical"),
    ("Business Intelligence",["business intelligence", "bi", "bi reporting", "bi tools"], "Technical"),
    ("Data Analysis",       ["data analysis", "data analytics", "exploratory data analysis"], "Technical"),
    # NOTE: "eda" removed — ambiguous (Exploratory Data Analysis vs Event-Driven Architecture).

    ("Statistics",          ["statistics", "statistical analysis", "stats", "statistical modeling", "probability", "quantitative analysis", "quant"], "Technical"),
    # NOTE: "quant" given here (Statistics/Quant Analysis). Quantitative Analysis dropped as separate canonical.

    ("Data Governance",     ["data governance", "data quality", "data lineage", "data catalog", "data mesh"], "Technical"),
    ("A/B Testing",         ["a/b testing", "ab testing", "split testing", "experimentation", "hypothesis testing"], "Technical"),
    ("High Availability",   ["high availability", "fault tolerance", "disaster recovery"], "Technical"),
    ("Performance Tuning",  ["performance tuning", "query optimization", "sql optimization", "performance optimization"], "Technical"),
    ("Security",            ["security", "cybersecurity", "information security", "infosec", "application security", "appsec"], "Technical"),
    ("OAuth",               ["oauth", "oauth 2.0", "oauth 1.0", "openid connect", "oidc"], "Technical"),
    # NOTE: "oauth2" excluded — too close to OAuth 2.0, redundant.

    ("JWT",                 ["jwt", "json web token", "bearer token"], "Technical"),
    ("Encryption",          ["encryption", "ssl", "tls", "ssl/tls", "https", "aes", "rsa encryption"], "Technical"),
    ("RBAC",                ["rbac", "role based access control", "access control list", "acl"], "Technical"),
    ("Observability",       ["observability", "distributed tracing", "apm", "application performance monitoring"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # DEVOPS — CONCEPT (ABSTRACT)
    # ═══════════════════════════════════════════════════════════════

    ("DevOps",              ["devops", "devsecops", "platform engineering"], "Technical"),
    ("CI/CD",               ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment", "devops pipeline"], "Technical"),
    ("Site Reliability Engineering", ["sre", "site reliability engineering", "site reliability engineer", "reliability engineering"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # OPERATING SYSTEMS & NETWORKING
    # ═══════════════════════════════════════════════════════════════

    ("Linux",               ["linux", "ubuntu", "debian", "centos", "rhel", "fedora", "unix", "linux administration", "linux server"], "Technical"),
    ("Networking",          ["networking", "tcp/ip", "dns", "vpn", "load balancing", "network protocols"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # TESTING
    # ═══════════════════════════════════════════════════════════════

    ("Unit Testing",        ["unit testing", "unit tests", "tdd", "test driven development", "pytest", "junit", "jest", "mocha", "jasmine"], "Technical"),
    ("Integration Testing", ["integration testing", "end-to-end testing", "e2e testing", "api testing", "cypress", "selenium", "playwright"], "Technical"),
    ("Test Automation",     ["test automation", "automated testing", "qa automation"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # MOBILE
    # ═══════════════════════════════════════════════════════════════

    ("Flutter",             ["flutter", "flutter dart", "flutter mobile"], "Technical"),
    ("iOS Development",     ["ios development", "ios app", "xcode", "swiftui", "uikit"], "Technical"),
    ("Android Development", ["android development", "android app", "android sdk", "android studio"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # EMERGING
    # ═══════════════════════════════════════════════════════════════

    ("Blockchain",          ["blockchain", "ethereum", "solidity", "smart contracts", "web3"], "Technical"),
    ("IoT",                 ["iot", "internet of things", "embedded systems", "mqtt", "edge computing"], "Technical"),

    # ═══════════════════════════════════════════════════════════════
    # TOOLS
    # ═══════════════════════════════════════════════════════════════

    ("Git",          ["git", "version control", "git version control", "source control"], "Tool"),
    ("GitHub",       ["github", "gh"], "Tool"),
    # R5: GitHub does NOT own "github actions" or "github workflows" — child canonical owns them.
    ("GitHub Actions", ["github actions", "gha", "github workflows", "github ci"], "Tool"),
    ("GitLab",         ["gitlab", "gitlab ci", "gitlab ci/cd"], "Tool"),
    ("Bitbucket",      ["bitbucket", "bitbucket pipelines"], "Tool"),
    # R5: "github actions" already claimed. CI/CD systems separated.

    ("Jenkins",   ["jenkins", "jenkins ci", "jenkins pipeline"], "Tool"),
    ("CircleCI",  ["circleci", "circle ci"], "Tool"),
    ("Travis CI", ["travis ci", "travis", "travisci"], "Tool"),
    ("ArgoCD",    ["argocd", "argo cd", "argo gitops", "argo workflows"], "Tool"),

    ("Jira",        ["jira", "jira software", "jira agile", "atlassian jira"], "Tool"),
    ("Confluence",  ["confluence", "atlassian confluence"], "Tool"),

    ("Prometheus",  ["prometheus", "prometheus monitoring"], "Tool"),
    ("Grafana",     ["grafana", "grafana dashboard"], "Tool"),
    ("Datadog",     ["datadog", "data dog"], "Tool"),
    ("New Relic",   ["new relic", "newrelic"], "Tool"),
    ("Splunk",      ["splunk", "splunk enterprise", "splunk siem"], "Tool"),
    ("OpenTelemetry",["opentelemetry", "otel", "open telemetry"], "Tool"),

    ("Tableau",     ["tableau", "tableau desktop", "tableau server", "tableau online", "tableau public"], "Tool"),
    ("Power BI",    ["power bi", "powerbi", "microsoft power bi", "pbix"], "Tool"),
    ("Looker",      ["looker", "looker studio", "google looker", "looker ml"], "Tool"),
    ("Metabase",    ["metabase"], "Tool"),
    ("Apache Superset", ["superset", "apache superset"], "Tool"),

    ("Fivetran",    ["fivetran"], "Tool"),
    ("Airbyte",     ["airbyte", "airbyte connector"], "Tool"),
    ("Stitch Data", ["stitch", "stitch data"], "Tool"),

    # R4: Apache ZooKeeper — single canonical. "Zookeeper" and "ZooKeeper" merged.
    ("Apache ZooKeeper", ["zookeeper", "apache zookeeper", "zk", "zookeeper cluster"], "Tool"),

    ("RabbitMQ",    ["rabbitmq", "rabbit mq", "amqp"], "Tool"),
    ("Celery",      ["celery", "celery workers", "celery beat", "celery queue"], "Tool"),

    # R4: Nginx and Apache HTTP — separated cleanly. No shared aliases.
    ("Nginx",         ["nginx", "nginx server", "nginx proxy", "nginx reverse proxy"], "Tool"),
    ("Apache HTTP Server", ["apache http server", "apache httpd", "httpd", "apache web server", "apache 2"], "Tool"),
    ("HAProxy",       ["haproxy", "ha proxy"], "Tool"),
    ("Istio",         ["istio", "istio service mesh", "service mesh"], "Tool"),
    ("Vault",         ["vault", "hashicorp vault", "secrets management", "secret manager"], "Tool"),
    ("Consul",        ["consul", "hashicorp consul", "service discovery"], "Tool"),

    ("Jupyter",       ["jupyter", "jupyter notebook", "jupyter lab", "jupyterlab", "ipython notebook"], "Tool"),
    ("VS Code",       ["vs code", "vscode", "visual studio code"], "Tool"),
    ("Postman",       ["postman", "postman api testing"], "Tool"),
    ("Swagger",       ["swagger", "openapi", "open api spec", "swagger ui"], "Tool"),
    ("SonarQube",     ["sonarqube", "sonar qube", "sonarcloud", "code quality tool"], "Tool"),

    # MLOps Tools
    ("MLflow",        ["mlflow", "ml flow", "mlflow tracking", "mlflow registry"], "Tool"),
    ("Weights & Biases",     ["wandb", "weights and biases", "weights & biases"], "Tool"),
    ("DVC",                  ["dvc", "data version control"], "Tool"),
    ("Great Expectations",   ["great expectations", "ge data quality"], "Tool"),

    ("Microsoft Excel",  ["excel", "ms excel", "microsoft excel", "vba", "excel vba", "pivot tables"], "Tool"),
    ("n8n",              ["n8n", "n8n automation"], "Tool"),

    # Kafka schema
    ("Kafka Schema Registry", ["schema registry", "confluent schema registry"], "Tool"),

    # ═══════════════════════════════════════════════════════════════
    # SOFT SKILLS
    # ═══════════════════════════════════════════════════════════════

    # R3: Agile does NOT own "scrum" — Scrum canonical owns it.
    ("Agile",          ["agile", "agile methodology", "agile development", "sprint", "kanban", "safe", "scaled agile"], "Soft Skill"),
    ("Scrum",          ["scrum", "scrum master", "scrum methodology", "sprint planning", "sprint review"], "Soft Skill"),
    ("Communication",  ["communication", "communication skills", "verbal communication", "written communication"], "Soft Skill"),
    ("Leadership",     ["leadership", "team lead", "tech lead", "technical lead", "engineering manager"], "Soft Skill"),
    ("Problem Solving",["problem solving", "analytical thinking", "critical thinking", "troubleshooting"], "Soft Skill"),
    ("Mentoring",      ["mentoring", "mentorship", "coaching", "knowledge sharing"], "Soft Skill"),
    ("Collaboration",  ["collaboration", "cross-functional", "teamwork"], "Soft Skill"),
    ("Documentation",  ["documentation", "technical writing", "writing docs", "readme writing"], "Soft Skill"),
    ("Code Review",    ["code review", "peer review", "pull request review", "pr review"], "Soft Skill"),
    ("Time Management",["time management", "prioritization", "deadline management"], "Soft Skill"),

    # ═══════════════════════════════════════════════════════════════
    # CERTIFICATIONS
    # ═══════════════════════════════════════════════════════════════

    ("AWS Certified",         ["aws certified", "aws solutions architect", "aws developer associate", "aws devops professional", "aws cloud practitioner", "aws sysops"], "Certification"),
    ("GCP Certified",         ["gcp certified", "google cloud certified", "google professional cloud architect", "google data engineer certification"], "Certification"),
    ("Azure Certified",       ["azure certified", "microsoft certified", "az-900", "az-104", "az-204", "az-305", "azure administrator", "azure developer"], "Certification"),
    ("Kubernetes Certified",  ["cka", "ckad", "cks", "certified kubernetes administrator", "certified kubernetes application developer"], "Certification"),
    ("Terraform Certified",   ["terraform certified", "hashicorp certified", "terraform associate"], "Certification"),
    ("Databricks Certified",  ["databricks certified", "databricks associate", "databricks professional", "databricks spark certification"], "Certification"),
    ("Snowflake Certified",   ["snowflake certified", "snowpro core", "snowpro advanced"], "Certification"),
    ("Scrum Certified",       ["csm", "certified scrum master", "psm", "professional scrum master"], "Certification"),
    ("PMP",                   ["pmp", "project management professional", "pmp certification"], "Certification"),
    ("CISSP",                 ["cissp", "certified information systems security professional"], "Certification"),
    ("SOC 2",                 ["soc 2", "soc2", "soc 2 compliance", "security compliance"], "Certification"),
    ("GDPR",                  ["gdpr", "data privacy", "privacy compliance", "data protection regulation"], "Certification"),
]


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION + WRITE
# ─────────────────────────────────────────────────────────────────────────────

def build_and_validate(raw):
    print(f"\n{'='*60}")
    print("Skill Taxonomy Generator — Validating...")
    print(f"{'='*60}")

    alias_owner: dict[str, str] = {}   # alias -> canonical
    errors = []
    docs = []

    for canonical, aliases, category in raw:
        normalized = []
        for alias in aliases:
            a = alias.strip().lower()
            if not a:
                continue
            if a in alias_owner:
                errors.append(
                    f"COLLISION: alias '{a}' claimed by both "
                    f"'{canonical}' and '{alias_owner[a]}'"
                )
            else:
                alias_owner[a] = canonical
                normalized.append(a)

        # Always ensure canonical itself is in alias list
        canon_lower = canonical.lower()
        if canon_lower not in alias_owner:
            alias_owner[canon_lower] = canonical
            normalized.append(canon_lower)

        docs.append({
            "canonical": canonical,
            "aliases":   normalized,
            "category":  category,
        })

    total_aliases = sum(len(d["aliases"]) for d in docs)
    total_skills  = len(docs)

    print(f"\n  Total canonical skills : {total_skills}")
    print(f"  Total aliases          : {total_aliases}")
    print(f"  Total collisions       : {len(errors)}")

    if errors:
        print("\n  COLLISIONS FOUND:")
        for e in errors:
            print(f"    X {e}")
        print("\nFix collisions before writing.")
        return None, errors

    # Category breakdown
    from collections import Counter
    cats = Counter(d["category"] for d in docs)
    print("\n  Breakdown by category:")
    for cat, count in sorted(cats.items()):
        print(f"    {cat:<20} {count}")

    print(f"\n{'='*60}")
    print("VALIDATION PASSED — Zero collisions.")
    print(f"{'='*60}\n")
    return docs, []


def write_json(docs):
    OUTPUT.write_text(
        json.dumps(docs, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"Written: {OUTPUT}")


if __name__ == "__main__":
    docs, errors = build_and_validate(RAW)
    if docs and not errors:
        write_json(docs)