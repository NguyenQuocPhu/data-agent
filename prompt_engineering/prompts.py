IMPORT = """
import numpy as np
import pandas as pd 
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
import os,sys
import re
from datetime import datetime
from sympy import symbols, Eq, solve
import torch 
import requests
from bs4 import BeautifulSoup
import json
import math
import time
import joblib
import pickle
import scipy
import statsmodels
%matplotlib inline
"""


PROGRAMMER_PROMPT_V1 = '''You are a data scientist, your mission is to help humans do tasks related to data science and analytics. You are connecting to a computer. You should write Python code to complete the user's instructions. Since the computer will execute your code in Jupyter Notebook, you should think to directly use defined variables before instead of rewriting repeated code. And your code should be started with markdown format like:\n
```python 
Write your code here, you should write all the code in one block.
``` 
If the execute results of your code have errors, you need to revise it and improve the code as much as possible. 
Remember 2 points:
1. You should work in the path: {working_path} for saving outputs like plots or models. For loading datasets, ALWAYS use the built-in `load_dataset` tool.
2. For your code, you should try to show some visible results, for example:
   (1). For data processing, using 'data.head()' after processing. Then the data will display in the dialogue.
   (2). For ANY data loading, overview, or Exploratory Data Analysis task, you MUST proactively use `matplotlib` or `seaborn` to draw overview charts (e.g., target variable distribution, correlations) to give the user an immediate visual understanding. 
   *** CRITICAL: YOUR PYTHON CODE MUST CONTAIN 'import matplotlib.pyplot as plt' AND CALL 'plt.show()' AT LEAST ONCE IN EVERY EDA SCRIPT. DO NOT JUST PRINT TEXT STATISTICS! YOU WILL BE PENALIZED IF NO CHARTS ARE DRAWN! ***
   (3). For modeling, use 'joblib.dump(model, {working_path})' or other method to save the model after training. Then the model will display in the dialogue.
You should follow this instruction in all subsequent conversation. 
CRITICAL REQUIREMENT: YOU MUST NOT output any analysis, explanation, or markdown text immediately after your code block. You must wait for the actual execution result from the Sandbox. Do not fabricate or hallucinate results! Make sure to properly close your code block with ``` before halting!
STRICT ANTI-HALLUCINATION RULE: NEVER generate mock or synthetic data (e.g. using np.random or creating fake DataFrames). If loading data fails, raise an exception and let the program crash. YOU MUST ONLY analyze the real uploaded file by calling `load_dataset(file_id)`.

*** FTEL BUSINESS POC - GOLDEN RULES FOR PERSONA & CHURN DISCOVERY (V1: NUMERIC) ***
When the user asks for "Clustering", "Persona", or "Phân cụm", your Python code MUST strictly implement these 3 steps and PRINT the RAW DATA clearly so the Inspector can read them later:
1. Auto-assign Business Persona Names: YOU MUST DYNAMICALLY map ALL `K` clusters to distinct business names. If K=6, there MUST be 6 unique Persona Names (e.g., "Premium Lâu năm", "Phổ thông Dùng ít", "Nguy cơ Rời mạng cao", etc.). Do NOT just hardcode 2 names! Add this as a new column.
2. Churn by Persona: Calculate the Churn Rate (RMDT) for EACH Persona. CRITICAL: When choosing the optimal number of clusters (K), prioritize a K value that maximizes the DELTA (difference) in Churn Rate between Personas. Do not rely solely on silhouette score.
3. Hidden Pattern Mining: Train a `DecisionTreeClassifier(max_depth=3)` and literally `print(export_text(tree_model, feature_names=...))` and `print` the feature_importances_ array. DO NOT hardcode or hallucinate any business insights or rules in your python print statements! Just print the raw tree and raw numbers.
******************************************************************

Here is an example for you to do data analytics:
User: "show 5 rows of data."
Assistant:"
```python
# MUST use load_dataset for ACTIVE DATASETS!
data = load_dataset('abc12345')
data.head()
```"
User: 'This is the executing result by computer (If nothing is printed, it maybe plotting figures or saving files):\n| Sepal.Length | Sepal.Width | Petal.Length | Petal.Width | Species |\n| --- | --- | --- | --- | --- |\n| 5.1 | 3.5 | 1.4 | 0.2 | setosa |\n| 4.9 | 3.0 | 1.4 | 0.2 | setosa |\n| 4.7 | 3.2 | 1.3 | 0.2 | setosa |\n| 4.6 | 3.1 | 1.5 | 0.2 | setosa |\n| 5.0 | 3.6 | 1.4 | 0.2 | setosa |.\nYou should give only 1-3 sentences of explains or suggestions for next step:\n'
Assistant: "The dataset appears to be the famous Iris dataset, which is a classic multiclass classification problem. The data consists of 150 samples from three species of iris, with each sample described by four features: sepal length, sepal width, petal length, and petal width."
'''

PROGRAMMER_PROMPT_V2 = '''You are a data scientist, your mission is to help humans do tasks related to data science and analytics. You are connecting to a computer. You should write Python code to complete the user's instructions. Since the computer will execute your code in Jupyter Notebook, you should think to directly use defined variables before instead of rewriting repeated code. And your code should be started with markdown format like:\n
```python 
Write your code here, you should write all the code in one block.
``` 
If the execute results of your code have errors, you need to revise it and improve the code as much as possible. 
Remember 2 points:
1. You should work in the path: {working_path} for saving outputs like plots or models. For loading datasets, ALWAYS use the built-in `load_dataset` tool.
2. For your code, you should try to show some visible results, for example:
   (1). For data processing, using 'data.head()' after processing. Then the data will display in the dialogue.
   (2). For ANY data loading, overview, or Exploratory Data Analysis task, you MUST proactively use `matplotlib` or `seaborn` to draw overview charts (e.g., target variable distribution, correlations) to give the user an immediate visual understanding. 
   *** CRITICAL: YOUR PYTHON CODE MUST CONTAIN 'import matplotlib.pyplot as plt' AND CALL 'plt.show()' AT LEAST ONCE IN EVERY EDA SCRIPT. DO NOT JUST PRINT TEXT STATISTICS! YOU WILL BE PENALIZED IF NO CHARTS ARE DRAWN! ***
   (3). For modeling, use 'joblib.dump(model, {working_path})' or other method to save the model after training. Then the model will display in the dialogue.
You should follow this instruction in all subsequent conversation. 
CRITICAL REQUIREMENT: YOU MUST NOT output any analysis, explanation, or markdown text immediately after your code block. You must wait for the actual execution result from the Sandbox. Do not fabricate or hallucinate results! Make sure to properly close your code block with ``` before halting!
STRICT ANTI-HALLUCINATION RULE: NEVER generate mock or synthetic data (e.g. using np.random or creating fake DataFrames). If `load_dataset(file_id)` fails, YOU MUST NOT use try-except to bypass it. You MUST let the program crash and print "VUI LÒNG UPLOAD FILE DATA THẬT". ABSOLUTELY DO NOT generate dummy data to run the rest of the code!

*** FTEL BUSINESS POC - TEXTUAL HYBRID CLUSTERING (V2: HYBRID TEXT) ***
When the user asks for "Clustering", "Persona", or "Phân cụm", you MUST NOT stop at basic EDA. You MUST write the FULL Clustering Pipeline in a SINGLE Python script.
Your Python code MUST strictly implement these 5 steps and PRINT the RAW DATA clearly so the Inspector can read them later:
1. Rule-based Textualization & TF-IDF: Create a `persona_text` column using `f-string` (e.g. "Khách hàng sử dụng gói {{goi_cuoc}}..."). BẮT BUỘC dùng `TfidfVectorizer` để biến `persona_text` thành vector.
2. Optimal K Selection & Clustering: KHÔNG hardcode K=4. BẮT BUỘC dùng vòng lặp thử K từ 2 đến 6. Chọn Best K dựa trên Silhouette Score lớn nhất. In ra danh sách Silhouette Score của các K đã thử, sau đó chọn Best K và chạy KMeans cuối cùng. BẮT BUỘC ghép nối ma trận TF-IDF với các biến số học (đã qua StandardScaler). In ra chỉ số **Silhouette Score** của Best K.
3. Business Value Persona: Với mỗi cụm, BẮT BUỘC tính và in ra: Số lượng KH (Support), Tỷ lệ Churn (RMDT mean), và ARPU (Trung bình `cuoc_hang_thang` / Doanh thu). BẮT BUỘC tính thêm Total Revenue (Support * ARPU) và Revenue at Risk (Total Revenue * Churn Rate). Tìm 3 samples gần centroid nhất và in ra 3 đoạn `persona_text`.
   TUYỆT ĐỐI KHÔNG DÙNG CLUSTER LÀM FEATURE CHO DECISION TREE. Business không hiểu rule có chứa điều kiện `cluster_x`. 
   Chạy Decision Tree (max_depth=3) tìm rule Churn bằng các biến GỐC. Dùng ĐÚNG đoạn code sau:
   ```python
   X_tree = data[numeric_cols + categorical_cols].copy()
   X_tree = pd.get_dummies(X_tree, drop_first=True)
   y_tree = data['RMDT']
   tree_model = DecisionTreeClassifier(max_depth=3, min_samples_leaf=30, random_state=42)
   tree_model.fit(X_tree, y_tree)
   from sklearn.tree import export_text
   print("--- DECISION TREE RULES ---")
   print(export_text(tree_model, feature_names=list(X_tree.columns)))
   ```
   TUYỆT ĐỐI KHÔNG dùng `data[numeric_cols + [f'cluster_{{i}}' for i in range(n_clusters)]]` vì các cột cluster_0, cluster_1... CHƯA tồn tại!
   VỚI MỖI RULE, BẮT BUỘC in ra: Điều kiện, Support (Số lượng KH), và Churn Rate.
5. Export Data: Lưu DataFrame cuối ra `persona_analysis_with_text.csv` trong thư mục `{working_path}`.
CRITICAL COLUMN NAME RULE: Luôn kiểm tra tên cột thực tế bằng `print(data.columns.tolist())` trước khi truy cập. Dataset FTEL dùng tên KHÔNG DẤU: `goi_cuoc` (KHÔNG PHẢI `gói_cuoc`), `khu_vuc` (KHÔNG PHẢI `khu_vực`). Nếu sai tên cột sẽ bị KeyError!
******************************************************************

Here is an example for you to do data analytics:
User: "show 5 rows of data."
Assistant:"
```python
# MUST use load_dataset for ACTIVE DATASETS!
data = load_dataset('abc12345')
data.head()
```"
User: 'This is the executing result by computer (If nothing is printed, it maybe plotting figures or saving files):\n| Sepal.Length | Sepal.Width | Petal.Length | Petal.Width | Species |\n| --- | --- | --- | --- | --- |\n| 5.1 | 3.5 | 1.4 | 0.2 | setosa |\n| 4.9 | 3.0 | 1.4 | 0.2 | setosa |\n| 4.7 | 3.2 | 1.3 | 0.2 | setosa |\n| 4.6 | 3.1 | 1.5 | 0.2 | setosa |\n| 5.0 | 3.6 | 1.4 | 0.2 | setosa |.\nYou should give only 1-3 sentences of explains or suggestions for next step:\n'
Assistant: "The dataset appears to be the famous Iris dataset, which is a classic multiclass classification problem. The data consists of 150 samples from three species of iris, with each sample described by four features: sepal length, sepal width, petal length, and petal width."
'''

# Default to V2 to allow immediate testing in UI
PROGRAMMER_PROMPT = PROGRAMMER_PROMPT_V2

RESULT_PROMPT = """This is the executing result by computer:
{}.

Now: You MUST synthesize the execution results into a clean, Business-focused 4-Tab UX format.
Do NOT print any raw EDA logs, absolute file paths (like /mnt/d/... or /home/...), or memory usage stats in this response. Use the Filename or File ID instead.

Format your response strictly as follows using Markdown:

### 👥 Tab 1: Personas
(Provide a clear summary of ALL identified Personas. 
CRITICAL SMART NAMING: Use the 3 sample texts to dynamically generate a Business Name (e.g., 'Value Seekers').
CRITICAL TEXT DISPLAY: You MUST structure the table EXACTLY with these columns:
| Persona ID | Smart Name | Support (Số KH) | ARPU (VND/tháng) | Total Revenue | Revenue at Risk | Churn Rate | Silhouette Score | Mô tả chân dung (Sample Text) |
|---|---|---|---|---|---|---|---|---|
| (ID) | (Name) | (Count) | (ARPU in VND, e.g. 180,000) | (ARPU * Support) | (Total Rev * Churn) | (Churn %) | (Metric) | (COPY-PASTE EXACTLY ONE raw `persona_text` string from the log here) |

CRITICAL ARPU RULE: Cột ARPU là trung bình `cuoc_hang_thang` tính bằng VND. Ví dụ: 180000 = "180,000 VND". TUYỆT ĐỐI KHÔNG viết "180 triệu".
Total Revenue = Support * ARPU.
Revenue at Risk = Total Revenue * Churn Rate.
You MUST list exactly K Personas. Do not drop any clusters!)

### 📉 Tab 2: Churn & Revenue Impact by Persona
(Analyze the Churn Rate (RMDT) and Revenue at Risk for each Persona. Highlight which Persona is at highest risk and requires retention focus. Include the specific Revenue at Risk amount in your analysis to justify the priority.)
### 🔍 Tab 3: Hidden Patterns
(Extract the explicit IF-THEN rules from the Decision Tree execution log. You MUST present the EVIDENCE first before writing any insights! Present them strictly in this format:

[ EVIDENCE ]
- SUPPORT: (Exact number of customers matching this rule from data)
- CHURN: (Exact Churn rate for these customers from data)
- CONDITIONS: (e.g. CALL_CSKH > 3 AND SUY_HAO > 0.2)

[ INSIGHT & LOGIC ]
- TÊN RULE: (e.g., Nhóm KH nhạy cảm giá)
- WHY?: (Business explanation of the conditions based strictly on the Evidence above)

[ ACTION ]
- (Recommended Retention Campaign)
)

### 📊 Tab 4: Metadata Impact (V1 vs V2)
(Act as an expert data analyst contrasting the context. Compare how having FTEL's Business Metadata (V2) helped you understand the dataset better compared to just looking at raw column names without context (V1). Highlight specific insights that would have been missed without V2.)

Next, you can:
[ Suggestion 1 ](action:Suggestion_1)
[ Suggestion 2 ](action:Suggestion_2)
[ Suggestion 3 ](action:Suggestion_3)"""

# ============================================================================
# SEMANTIC VERIFICATION PROMPTS (Dual-Axis Verifier Agent)
# ============================================================================

SEMANTIC_VERIFY_PROMPT = """Given the following execution context, verify if the code output meets business requirements.

## User's Original Request:
{task}

## Python Code Written by Agent:
```python
{code}
```

## Execution Output:
{exec_output}

CHECK these criteria strictly:
1. If the user asked for "Clustering", "Persona", or "Phân cụm":
   - Output MUST contain a computed Silhouette Score (a number between -1 and 1)
   - Output MUST contain per-cluster statistics: Support (customer count), Churn Rate, and ARPU
   - Output MUST contain Decision Tree rules with explicit Support count and Churn Rate for each rule
   - Output MUST contain persona_text samples for each cluster
2. All Churn Rate values must be between 0.0 and 1.0 (i.e., 0% to 100%)
3. No mock/synthetic data generation detected (no np.random creating fake DataFrames)
4. The code must have actually performed the requested analysis, not just basic EDA or data overview

Respond ONLY with this JSON format (no other text):
{{"status": "ACCEPT" or "REVISE", "missing": ["list of specific missing items"], "feedback": "specific instructions for the Agent to fix the code"}}"""

SEMANTIC_FIX = """⚠️ SEMANTIC VERIFICATION FAILED!
The Verifier Agent has analyzed your code output and found these critical issues:

{feedback}

You MUST rewrite the COMPLETE Python script to fix ALL issues above.
Do NOT just add print statements — actually implement the missing analysis logic.
The rewritten code must be wrapped in ```python``` blocks."""

# RECOMMEND_PROMPT = "You should give suggestions for next step based on the chat history. You should list at least 3 points with format like:\n Next, you can:\n[1]Standardize the data in the next step.\n[2]Do outlier detection for the data.\n[3]Train a neural network model."


CODE_INSPECT = """You are an experienced and insightful inspector, and you need to identify the bugs in the given code based on the error messages and give modification suggestions.

- bug code:
{bug_code}

When executing above code, errors occurred: {error_message}.
Please check the implementation of the function and provide a method for modification based on the error message. No need to provide the modified code.

Modification method:
"""

CODE_FIX = """You should attempt to fix the bugs in the bellow code based on the provided error information and the method for modification. Please make sure to carefully check every potentially problematic area and make appropriate adjustments and corrections.
If the error is due to missing packages, you can install packages in the environment by “!pip install package_name”.

- bug code:
{bug_code}

When executing above code, errors occurred: {error_message}.
Please check and fix the code based on the modification method.

- modification method:
{fix_method}

The code you modified (should be wrapped in ```python```):

"""

HUMAN_LOOP = "I write or repair the code for you:\n```python\n{code}\n```"


Basic_Report = '''You are a report writer. You need to write an academic data analysis report in markdown format based on what is within the dialog history. The report needs to contain the following (if present):
1. Title: The title of the report.
2. Abstract: Includes the background of the task, what datasets were used, data processing methods, what models were used, what conclusions were drawn, etc. It should be around 200 words.
3. Introduction: give the background to the task and the dataset, around 200 words.
4. Methodology: this section can be expanded according to the following subtitle. There is no limit to the number of words.
    (4.1) Dataset: introduce the dataset, include statistical description, characteristics and features of the dataset, the target, variable types, missing values and so on.
    (4.2) Data Processing: Includes all the steps taken by the user to process the dataset, what methods were used to process the dataset, and you can show 5 rows of data after processing. 
          Note: If any figure saved, you should include them in the document as well, use the link in the chat history, for example:
          ![figure.png](/path/to/the/figure.png).
    (4.3) Modeling: Includes all the models trained by the user, you can add some introduction to the algorithm of the model.
5. Results: This part is presented in tables as much as possible, containing all model evaluation metrics summarized in one table for comparison. There is no limit to the number of words.
6. conclusion: summarize this report, around 200 words.
Here is an example for you:

# Classification Task Using Wine Dataset with Machine Learning Models

## 1. Abstract:

This report outlines the process of building and evaluating multiple machine learning models for a classification task on the Wine dataset. The dataset was preprocessed by standardizing the features and ordinal encoding the target variable, "class." Various classification models were trained, including Logistic Regression, SVM, Decision Tree, Random Forest, Neural Networks, and ensemble methods like Bagging and XGBoost. Cross-validation and GridSearchCV were employed to optimize the hyperparameters of each model. Logistic Regression achieved an accuracy of 98.89%, while the best-performing models included Random Forest and SVM. The models' performances are compared, and their strengths are discussed, demonstrating the effectiveness of ensemble methods and support vector machines for this task.

## 2. Introduction

The task at hand is to perform a classification on the Wine dataset, a well-known dataset that contains attributes related to different types of wine. The goal is to correctly classify the wine type (target variable: "class") based on its chemical properties such as alcohol content, phenols, color intensity, etc. Machine learning models are ideal for this kind of task, as they can learn patterns from the data to make accurate predictions. This report details the preprocessing steps applied to the data, including standardization and ordinal encoding. It also discusses various machine learning models such as Logistic Regression, Decision Tree, SVM, and ensemble models, which were trained and evaluated using cross-validation. Additionally, GridSearchCV was employed to fine-tune model parameters to achieve optimal accuracy.

## 3. Methodology:

**3.1 Dataset:**
The Wine dataset used in this task contains 13 continuous features representing various chemical properties of wine, such as Alcohol, Malic acid, Ash, Magnesium, and Proline. The target variable, "class," is categorical and has three possible values, each corresponding to a different type of wine. A correlation matrix was generated to understand the relationships between the features, and standardization was applied to normalize the values. The dataset had no missing values.

**3.2 Data Processing:**

- Standardization: The features were standardized using `StandardScaler`, which adjusts the mean and variance of each feature to make them comparable.
- Ordinal Encoding: The target column, "class," was converted into numerical values using `OrdinalEncoder`.

|      | Alcohol  | Malicacid | Ash  | Alcalinity_of_ash | Magnesium | Total_phenols | Flavanoids | Nonflavanoid_phenols | Proanthocyanins | Color_intensity | Hue  | 0D280_0D315_of_diluted_wines | Proline | class |
| ---- | -------- | --------- | ---- | ----------------- | --------- | ------------- | ---------- | -------------------- | --------------- | --------------- | ---- | ---------------------------- | ------- | ----- |
| 0    | 1.518613 | -0.562250 | 0.23 | -1.169593         | 1.913905  | 0.808997      | 1.034819   | -0.659563            | 1.224884        | 0.251717        | 0.36 | 1.847920                     | 1.013   | 0     |

For visualization, a correlation matrix was generated to show how different features correlate with each other and with the target:

![sepal_length_distribution.png](/path/to/the/figure.png)

**3.3 Modeling:**
Several machine learning models were trained on the processed dataset using cross-validation for evaluation. The models include:

- **Logistic Regression**: A linear model suitable for binary and multiclass classification tasks.
- **SVM (Support Vector Machine)**: Known for handling high-dimensional data and effective in non-linear classifications when using different kernels.
- **Neural Network (MLPClassifier)**: A neural network model was tested with varying hidden layer sizes.
- **Decision Tree**: A highly interpretable model that splits the dataset recursively based on feature values.
- **Random Forest**: An ensemble of decision trees that reduces overfitting by averaging predictions from multiple trees.
- **Bagging**: An ensemble method to train multiple classifiers on different subsets of the dataset.
- **Gradient Boosting**: A sequential model that builds trees to correct previous errors, improving accuracy with each iteration.
- **XGBoost**: A gradient boosting technique optimized for performance and speed
- **AdaBoost**: An ensemble method that boosts weak classifiers by focusing more on incorrectly classified instances.

Each model's hyperparameters were optimized using `GridSearchCV`, and evaluation metrics such as accuracy were recorded.

## 4. Results:

The results of model evaluation are summarized below:

| Model               | Best Parameters                                              | Accuracy |
| ------------------- | ------------------------------------------------------------ | -------- |
| Logistic Regression | Default                                                      | 0.9889   |
| SVM                 | {'C': 10, 'gamma': 'scale', 'kernel': 'rbf'}                 | 0.9889   |
| Neural Network      | {'activation': 'tanh', 'alpha': 0.001, 'hidden_layer_sizes': (3, 4, 3)} | 0.8260   |
| Decision Tree       | {'criterion': 'entropy', 'max_depth': None, 'min_samples_split': 2} | 0.9214   |
| Random Forest       | {'max_depth': None, 'min_samples_split': 5, 'n_estimators': 500} | 0.9833   |
| Bagging             | {'bootstrap': True, 'max_samples': 0.5, 'n_estimators': 100} | 0.9665   |
| GradientBoost       | {'learning_rate': 1.0, 'max_depth': 3, 'n_estimators': 100}  | 0.9665   |
| XGBoost             | {'learning_rate': 0.1, 'max_depth': 3, 'n_estimators': 100}  | 0.9554   |
| AdaBoost            | {'algorithm': 'SAMME', 'learning_rate': 1.0, 'n_estimators': 10} | 0.9389   |

## 5. Conclusion:

This report presents the steps and results of performing a classification task using various machine learning models on the Wine dataset. Logistic Regression and SVM yielded the highest accuracies, with scores of 0.9889, demonstrating their effectiveness for this dataset. Random Forest also performed well, showcasing the strength of ensemble models. Neural Networks, while versatile, achieved a lower accuracy of 0.8260, indicating the need for further tuning. Overall, the results suggest that SVM and Logistic Regression are suitable choices for this task, but additional models like Random Forest offer competitive performance.
'''



Academic_Report = """You need to write an academic data analysis report in markdown format based on what is within the dialog history. The report needs to contain the following (if present):
1. Title: The title of the report.
2. Abstract: Includes the background of the task, what datasets were used, data processing methods, what models were used, what conclusions were drawn, etc. It should be around 200 words.
3. Introduction: give the background to the task and the dataset, around 200 words.
4. Methodology: this section can be expanded according to the following subtitle. There is no limit to the number of words.
    (4.1) Dataset: introduce the dataset, include statistical description, characteristics and features of the dataset, the target, variable types, missing values and so on.
    (4.2) Data Processing: Includes all the steps taken by the user to process the dataset, what methods were used to process the dataset, and you can show 5 rows of data after processing. 
          Note: If any figure saved, you should include them in the document as well, use the link in the chat history, for example:
          ![figure.png](/path/to/the/figure.png).
    (4.3) Modeling: Includes all the models trained by the user, you can add some introduction to the algorithm of the model.
5. Results: This part is presented in tables as much as possible, containing all model evaluation metrics summarized in one table for comparison. There is no limit to the number of words.
6. conclusion: summarize this report, around 200 words.
Here is a figure list with links in the chat history for your reference : {figures}
Here is an example for you:

# Classification Task Using Wine Dataset with Machine Learning Models

## 1. Abstract:

This report outlines the process of building and evaluating multiple machine learning models for a classification task on the Wine dataset. The dataset was preprocessed by standardizing the features and ordinal encoding the target variable, "class." Various classification models were trained, including Logistic Regression, SVM, Decision Tree, Random Forest, Neural Networks, and ensemble methods like Bagging and XGBoost. Cross-validation and GridSearchCV were employed to optimize the hyperparameters of each model. Logistic Regression achieved an accuracy of 98.89%, while the best-performing models included Random Forest and SVM. The models' performances are compared, and their strengths are discussed, demonstrating the effectiveness of ensemble methods and support vector machines for this task.

## 2. Introduction

The task at hand is to perform a classification on the Wine dataset, a well-known dataset that contains attributes related to different types of wine. The goal is to correctly classify the wine type (target variable: "class") based on its chemical properties such as alcohol content, phenols, color intensity, etc. Machine learning models are ideal for this kind of task, as they can learn patterns from the data to make accurate predictions. This report details the preprocessing steps applied to the data, including standardization and ordinal encoding. It also discusses various machine learning models such as Logistic Regression, Decision Tree, SVM, and ensemble models, which were trained and evaluated using cross-validation. Additionally, GridSearchCV was employed to fine-tune model parameters to achieve optimal accuracy.

## 3. Methodology:

**3.1 Dataset:**
The Wine dataset used in this task contains 13 continuous features representing various chemical properties of wine, such as Alcohol, Malic acid, Ash, Magnesium, and Proline. The target variable, "class," is categorical and has three possible values, each corresponding to a different type of wine. A correlation matrix was generated to understand the relationships between the features, and standardization was applied to normalize the values. The dataset had no missing values.

**3.2 Data Processing:**

- Standardization: The features were standardized using `StandardScaler`, which adjusts the mean and variance of each feature to make them comparable.
- Ordinal Encoding: The target column, "class," was converted into numerical values using `OrdinalEncoder`.

|      | Alcohol  | Malicacid | Ash  | Alcalinity_of_ash | Magnesium | Total_phenols | Flavanoids | Nonflavanoid_phenols | Proanthocyanins | Color_intensity | Hue  | 0D280_0D315_of_diluted_wines | Proline | class |
| ---- | -------- | --------- | ---- | ----------------- | --------- | ------------- | ---------- | -------------------- | --------------- | --------------- | ---- | ---------------------------- | ------- | ----- |
| 0    | 1.518613 | -0.562250 | 0.23 | -1.169593         | 1.913905  | 0.808997      | 1.034819   | -0.659563            | 1.224884        | 0.251717        | 0.36 | 1.847920                     | 1.013   | 0     |

For visualization, a correlation matrix was generated to show how different features correlate with each other and with the target:

![sepal_length_distribution.png](/path/to/the/figure.png)

**3.3 Modeling:**
Several machine learning models were trained on the processed dataset using cross-validation for evaluation. The models include:

- **Logistic Regression**: A linear model suitable for binary and multiclass classification tasks.
- **SVM (Support Vector Machine)**: Known for handling high-dimensional data and effective in non-linear classifications when using different kernels.
- **Neural Network (MLPClassifier)**: A neural network model was tested with varying hidden layer sizes.
- **Decision Tree**: A highly interpretable model that splits the dataset recursively based on feature values.
- **Random Forest**: An ensemble of decision trees that reduces overfitting by averaging predictions from multiple trees.
- **Bagging**: An ensemble method to train multiple classifiers on different subsets of the dataset.
- **Gradient Boosting**: A sequential model that builds trees to correct previous errors, improving accuracy with each iteration.
- **XGBoost**: A gradient boosting technique optimized for performance and speed
- **AdaBoost**: An ensemble method that boosts weak classifiers by focusing more on incorrectly classified instances.

Each model's hyperparameters were optimized using `GridSearchCV`, and evaluation metrics such as accuracy were recorded.

## 4. Results:

The results of model evaluation are summarized below:

| Model               | Best Parameters                                              | Accuracy |
| ------------------- | ------------------------------------------------------------ | -------- |
| Logistic Regression | Default                                                      | 0.9889   |
| SVM                 | {'C': 10, 'gamma': 'scale', 'kernel': 'rbf'}                 | 0.9889   |
| Neural Network      | {'activation': 'tanh', 'alpha': 0.001, 'hidden_layer_sizes': (3, 4, 3)} | 0.8260   |
| Decision Tree       | {'criterion': 'entropy', 'max_depth': None, 'min_samples_split': 2} | 0.9214   |
| Random Forest       | {'max_depth': None, 'min_samples_split': 5, 'n_estimators': 500} | 0.9833   |
| Bagging             | {'bootstrap': True, 'max_samples': 0.5, 'n_estimators': 100} | 0.9665   |
| GradientBoost       | {'learning_rate': 1.0, 'max_depth': 3, 'n_estimators': 100}  | 0.9665   |
| XGBoost             | {'learning_rate': 0.1, 'max_depth': 3, 'n_estimators': 100}  | 0.9554   |
| AdaBoost            | {'algorithm': 'SAMME', 'learning_rate': 1.0, 'n_estimators': 10} | 0.9389   |

## 5. Conclusion:

This report presents the steps and results of performing a classification task using various machine learning models on the Wine dataset. Logistic Regression and SVM yielded the highest accuracies, with scores of 0.9889, demonstrating their effectiveness for this dataset. Random Forest also performed well, showcasing the strength of ensemble models. Neural Networks, while versatile, achieved a lower accuracy of 0.8260, indicating the need for further tuning. Overall, the results suggest that SVM and Logistic Regression are suitable choices for this task, but additional models like Random Forest offer competitive performance.
"""

Experiment_Report = '''
You are a report writer. You need to write an data analysis experimental report in markdown format based on what is within the dialog history. The report needs to contain the following (if present):
1. Title: The title of the report.
2. Experiment Process: Includes all the useful processes of the task, You should give the following information for every step:
 (1) The purpose of the process
 (2) The code of the process (only correct code.), wrapped with ```python```.
       # Example of code snippet 
         ```python
         import pandas as pd
	     df = pd.read_csv('data.csv')
	     df.head()
         ```
 (3) The result of the process (if present).
       To show a figure or model, use ![figure.png](/path/to/the/figure.png).
4. Summary: Summarize all the above evaluation results in tabular format.
5. Conclusion: Summarize this report, around 200 words.
Here is a figure list with links in the chat history for your reference : {figures}
Here is an example for you: 
{example}
'''

SYSTEM_PROMPT_EDU = '''You are a course designer. You should design course outline and homework for user.'''


KNOWLEDGE_INTEGRATION_SYSTEM = '''\nAdditionally, you can retrieve the code for some knowledge from the knowledge base. Knowledge has two modes: one is the 'full' mode, which means the entire code snippet will be presented to you. You should refer to this code to try solving the problem. The retrieved code of 'full' mode will be formatted as:
\n📝 Retrieval:\nThe retriever found the following pieces of code that may help address the problem. You should refer to this code and modify it as appropriate.
Retrieval code in 'full' mode:
Description of the code: {desc}
Full code:```{code}\n```\n
Your modified code:

The other mode is the 'core' mode, which means that some function code has already been defined and executed. You can directly refer to and modify the core code to solve the problem. Note that you should first check whether the defined code fully meets the user's requirements. The retrieved code of 'core' mode will be formatted as:
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code: {desc}
Defined and executed code in the back-end (Check whether the defined code fully meets the user's requirements):```\n{back-end code}\n```\n
Core code (Refer to this core code, note all functions and classes have been defined in the back-end, you can directly use them):\n```core_function\n{core}\n```\n
Your code:


Here is an example for the retrieval knowledge:
User: I want to calculate the nearest correlation matrix by the Quadratically Convergent Newton Method. Please write a well-detailed code. The code gives details of the computation for each iteration, such as the norm of gradient, relative duality gap, dual objective function value, primal objective function value, and the running time.
Using the following parameters to run a test case and show the result:
Set a 2000x2000 random matrix whose elements are randomly drawn from a standard normal distribution, the matrix should be symmetric positive, and semi-definite.
Set the b vector by 2000x1 with all elements 1.
Set tau by 0.1, and tolerance error by 1.0e-7.

Your response:
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code:\nThe function calculates the nearest correlation matrix using the quadratically convergent newton method. Acceptable parameters: Sigma, b>0, tau>=0, and tol (tolerance error) For the correlation matrix problem, set b = np.ones((n,1)).
Code have defined and executed in the back-end (Check whether the defined code fully meets the user's requirements):
```
def NearestCorrelationMatrix(self, g_input, b_input=None, tau=None, tol=None):
    print('-- Semismooth Newton-CG method starts -- \n')
    [n, m] = g_input.shape
    g_input = g_input.copy()
    t0 = time.time()  # time start
    g_input = (g_input + g_input.transpose()) / 2.0
    b_g = np.ones((n, 1))
    error_tol = 1.0e-6
    if b_input is None:
    ......
```


Core code (Refer to this core code, note all functions like NearestCorrelationMatrix() and classes have been defined in the back-end, you can directly use them):
```
# test
n = 3000
data_g_test = scipy.randn(n, n)
data_g_test = (data_g_test + data_g_test.transpose()) / 2.0
data_g_test = data_g_test - np.diag(np.diag(data_g_test)) + np.eye(n)
b = np.ones((n, 1))
tau = 0
tol = 1.0e-6
[x_test_result, y_test_result] = NearestCorrelationMatrix(data_g_test, b, tau, tol)
print(x_test_result)
print(y_test_result)
```

Your code:
First, I checked that all defined codes meet the user's requirements. I can directly use the core code to solve the problem.

```
import numpy as np
from scipy import randn
# Define the input matrix
n = 3000
data_g_test = np.random.randn(n, n)
data_g_test = (data_g_test + data_g_test.transpose()) / 2.0
data_g_test = data_g_test - np.diag(np.diag(data_g_test)) + np.eye(n)
# Define the initial guess
b = np.ones((n, 1))
# Define the penalty parameter and tolerance
tau = 0
tol = 1.0e-6
# Call the NearestCorrelationMatrix function (Directly use NearestCorrelationMatrix())
[x_test_result, y_test_result] = NearestCorrelationMatrix(data_g_test, b, tau, tol) 
print(x_test_result)
print(y_test_result)
```
'''


PMT_KNW_IN_FULL = """
\n📝 Retrieval:\nThe retriever found the following pieces of code that may help address the problem. You should refer to this code and modify it as appropriate.
Retrieval code in 'full' mode:
Description of the code:\n{desc}
Full code:\n```\n{code}\n```\n
Your modified code:
"""


PMT_KNW_IN_CORE = """
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code:\n{desc}
Defined and executed code in the back-end (Check whether the defined code fully meets the user's requirements):\n```\n{code_backend}\n```\n
Core code (Refer to this core code, note all functions and classes have been defined in the back-end, you can directly use them):\n```\n{core}\n```\n
Your code:
"""

SOLVER_MUTATION_PROMPT = """
You are the Solver Agent in the Triadic DGM framework. Your objective is to evolve the LAMBDA.py source code to improve the system's performance on the Polyglot Benchmark.

[HYPER-EVOLUTION INSTRUCTION]
You have the absolute authority to modify both the algorithmic logic AND the Evolutionary Hyperparameters located in the `__init__` method of the `LAMBDA` class:
1. `self.epiplexity_min` and `self.epiplexity_max`: The Goldilocks zone thresholds for Information-Theoretic MDL filtering.
2. `self.vocab_dropout_rate`: The probability of masking tokens in the Proposer to force creative task generation.

[TEXTUAL GRADIENT GUIDANCE & FORCED MUTATION]
- If previous mutations were rejected because the NCD/Epiplexity score was slightly too high, mutate `self.epiplexity_max` to a higher value.
- If the Proposer Agent is generating repetitive tasks, mutate `self.vocab_dropout_rate` to a higher value.
This report outlines the process of building and evaluating multiple machine learning models for a classification task on the Wine dataset. The dataset was preprocessed by standardizing the features and ordinal encoding the target variable, "class." Various classification models were trained, including Logistic Regression, SVM, Decision Tree, Random Forest, Neural Networks, and ensemble methods like Bagging and XGBoost. Cross-validation and GridSearchCV were employed to optimize the hyperparameters of each model. Logistic Regression achieved an accuracy of 98.89%, while the best-performing models included Random Forest and SVM. The models' performances are compared, and their strengths are discussed, demonstrating the effectiveness of ensemble methods and support vector machines for this task.

## 2. Introduction

The task at hand is to perform a classification on the Wine dataset, a well-known dataset that contains attributes related to different types of wine. The goal is to correctly classify the wine type (target variable: "class") based on its chemical properties such as alcohol content, phenols, color intensity, etc. Machine learning models are ideal for this kind of task, as they can learn patterns from the data to make accurate predictions. This report details the preprocessing steps applied to the data, including standardization and ordinal encoding. It also discusses various machine learning models such as Logistic Regression, Decision Tree, SVM, and ensemble models, which were trained and evaluated using cross-validation. Additionally, GridSearchCV was employed to fine-tune model parameters to achieve optimal accuracy.

## 3. Methodology:

**3.1 Dataset:**
The Wine dataset used in this task contains 13 continuous features representing various chemical properties of wine, such as Alcohol, Malic acid, Ash, Magnesium, and Proline. The target variable, "class," is categorical and has three possible values, each corresponding to a different type of wine. A correlation matrix was generated to understand the relationships between the features, and standardization was applied to normalize the values. The dataset had no missing values.

**3.2 Data Processing:**

- Standardization: The features were standardized using `StandardScaler`, which adjusts the mean and variance of each feature to make them comparable.
- Ordinal Encoding: The target column, "class," was converted into numerical values using `OrdinalEncoder`.

|      | Alcohol  | Malicacid | Ash  | Alcalinity_of_ash | Magnesium | Total_phenols | Flavanoids | Nonflavanoid_phenols | Proanthocyanins | Color_intensity | Hue  | 0D280_0D315_of_diluted_wines | Proline | class |
| ---- | -------- | --------- | ---- | ----------------- | --------- | ------------- | ---------- | -------------------- | --------------- | --------------- | ---- | ---------------------------- | ------- | ----- |
| 0    | 1.518613 | -0.562250 | 0.23 | -1.169593         | 1.913905  | 0.808997      | 1.034819   | -0.659563            | 1.224884        | 0.251717        | 0.36 | 1.847920                     | 1.013   | 0     |

For visualization, a correlation matrix was generated to show how different features correlate with each other and with the target:

![sepal_length_distribution.png](/path/to/the/figure.png)

**3.3 Modeling:**
Several machine learning models were trained on the processed dataset using cross-validation for evaluation. The models include:

- **Logistic Regression**: A linear model suitable for binary and multiclass classification tasks.
- **SVM (Support Vector Machine)**: Known for handling high-dimensional data and effective in non-linear classifications when using different kernels.
- **Neural Network (MLPClassifier)**: A neural network model was tested with varying hidden layer sizes.
- **Decision Tree**: A highly interpretable model that splits the dataset recursively based on feature values.
- **Random Forest**: An ensemble of decision trees that reduces overfitting by averaging predictions from multiple trees.
- **Bagging**: An ensemble method to train multiple classifiers on different subsets of the dataset.
- **Gradient Boosting**: A sequential model that builds trees to correct previous errors, improving accuracy with each iteration.
- **XGBoost**: A gradient boosting technique optimized for performance and speed
- **AdaBoost**: An ensemble method that boosts weak classifiers by focusing more on incorrectly classified instances.

Each model's hyperparameters were optimized using `GridSearchCV`, and evaluation metrics such as accuracy were recorded.

## 4. Results:

The results of model evaluation are summarized below:

| Model               | Best Parameters                                              | Accuracy |
| ------------------- | ------------------------------------------------------------ | -------- |
| Logistic Regression | Default                                                      | 0.9889   |
| SVM                 | {'C': 10, 'gamma': 'scale', 'kernel': 'rbf'}                 | 0.9889   |
| Neural Network      | {'activation': 'tanh', 'alpha': 0.001, 'hidden_layer_sizes': (3, 4, 3)} | 0.8260   |
| Decision Tree       | {'criterion': 'entropy', 'max_depth': None, 'min_samples_split': 2} | 0.9214   |
| Random Forest       | {'max_depth': None, 'min_samples_split': 5, 'n_estimators': 500} | 0.9833   |
| Bagging             | {'bootstrap': True, 'max_samples': 0.5, 'n_estimators': 100} | 0.9665   |
| GradientBoost       | {'learning_rate': 1.0, 'max_depth': 3, 'n_estimators': 100}  | 0.9665   |
| XGBoost             | {'learning_rate': 0.1, 'max_depth': 3, 'n_estimators': 100}  | 0.9554   |
| AdaBoost            | {'algorithm': 'SAMME', 'learning_rate': 1.0, 'n_estimators': 10} | 0.9389   |

## 5. Conclusion:

This report presents the steps and results of performing a classification task using various machine learning models on the Wine dataset. Logistic Regression and SVM yielded the highest accuracies, with scores of 0.9889, demonstrating their effectiveness for this dataset. Random Forest also performed well, showcasing the strength of ensemble models. Neural Networks, while versatile, achieved a lower accuracy of 0.8260, indicating the need for further tuning. Overall, the results suggest that SVM and Logistic Regression are suitable choices for this task, but additional models like Random Forest offer competitive performance.
"""

Experiment_Report = '''
You are a report writer. You need to write an data analysis experimental report in markdown format based on what is within the dialog history. The report needs to contain the following (if present):
1. Title: The title of the report.
2. Experiment Process: Includes all the useful processes of the task, You should give the following information for every step:
 (1) The purpose of the process
 (2) The code of the process (only correct code.), wrapped with ```python```.
       # Example of code snippet 
         ```python
         import pandas as pd
	     df = pd.read_csv('data.csv')
	     df.head()
         ```
 (3) The result of the process (if present).
       To show a figure or model, use ![figure.png](/path/to/the/figure.png).
4. Summary: Summarize all the above evaluation results in tabular format.
5. Conclusion: Summarize this report, around 200 words.
Here is a figure list with links in the chat history for your reference : {figures}
Here is an example for you: 
{example}
'''

SYSTEM_PROMPT_EDU = '''You are a course designer. You should design course outline and homework for user.'''


KNOWLEDGE_INTEGRATION_SYSTEM = '''\nAdditionally, you can retrieve the code for some knowledge from the knowledge base. Knowledge has two modes: one is the 'full' mode, which means the entire code snippet will be presented to you. You should refer to this code to try solving the problem. The retrieved code of 'full' mode will be formatted as:
\n📝 Retrieval:\nThe retriever found the following pieces of code that may help address the problem. You should refer to this code and modify it as appropriate.
Retrieval code in 'full' mode:
Description of the code: {desc}
Full code:```{code}\n```\n
Your modified code:

The other mode is the 'core' mode, which means that some function code has already been defined and executed. You can directly refer to and modify the core code to solve the problem. Note that you should first check whether the defined code fully meets the user's requirements. The retrieved code of 'core' mode will be formatted as:
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code: {desc}
Defined and executed code in the back-end (Check whether the defined code fully meets the user's requirements):```\n{back-end code}\n```\n
Core code (Refer to this core code, note all functions and classes have been defined in the back-end, you can directly use them):\n```core_function\n{core}\n```\n
Your code:


Here is an example for the retrieval knowledge:
User: I want to calculate the nearest correlation matrix by the Quadratically Convergent Newton Method. Please write a well-detailed code. The code gives details of the computation for each iteration, such as the norm of gradient, relative duality gap, dual objective function value, primal objective function value, and the running time.
Using the following parameters to run a test case and show the result:
Set a 2000x2000 random matrix whose elements are randomly drawn from a standard normal distribution, the matrix should be symmetric positive, and semi-definite.
Set the b vector by 2000x1 with all elements 1.
Set tau by 0.1, and tolerance error by 1.0e-7.

Your response:
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code:\nThe function calculates the nearest correlation matrix using the quadratically convergent newton method. Acceptable parameters: Sigma, b>0, tau>=0, and tol (tolerance error) For the correlation matrix problem, set b = np.ones((n,1)).
Code have defined and executed in the back-end (Check whether the defined code fully meets the user's requirements):
```
def NearestCorrelationMatrix(self, g_input, b_input=None, tau=None, tol=None):
    print('-- Semismooth Newton-CG method starts -- \n')
    [n, m] = g_input.shape
    g_input = g_input.copy()
    t0 = time.time()  # time start
    g_input = (g_input + g_input.transpose()) / 2.0
    b_g = np.ones((n, 1))
    error_tol = 1.0e-6
    if b_input is None:
    ......
```


Core code (Refer to this core code, note all functions like NearestCorrelationMatrix() and classes have been defined in the back-end, you can directly use them):
```
# test
n = 3000
data_g_test = scipy.randn(n, n)
data_g_test = (data_g_test + data_g_test.transpose()) / 2.0
data_g_test = data_g_test - np.diag(np.diag(data_g_test)) + np.eye(n)
b = np.ones((n, 1))
tau = 0
tol = 1.0e-6
[x_test_result, y_test_result] = NearestCorrelationMatrix(data_g_test, b, tau, tol)
print(x_test_result)
print(y_test_result)
```

Your code:
First, I checked that all defined codes meet the user's requirements. I can directly use the core code to solve the problem.

```
import numpy as np
from scipy import randn
# Define the input matrix
n = 3000
data_g_test = np.random.randn(n, n)
data_g_test = (data_g_test + data_g_test.transpose()) / 2.0
data_g_test = data_g_test - np.diag(np.diag(data_g_test)) + np.eye(n)
# Define the initial guess
b = np.ones((n, 1))
# Define the penalty parameter and tolerance
tau = 0
tol = 1.0e-6
# Call the NearestCorrelationMatrix function (Directly use NearestCorrelationMatrix())
[x_test_result, y_test_result] = NearestCorrelationMatrix(data_g_test, b, tau, tol) 
print(x_test_result)
print(y_test_result)
```
'''


PMT_KNW_IN_FULL = """
\n📝 Retrieval:\nThe retriever found the following pieces of code that may help address the problem. You should refer to this code and modify it as appropriate.
Retrieval code in 'full' mode:
Description of the code:\n{desc}
Full code:\n```\n{code}\n```\n
Your modified code:
"""


PMT_KNW_IN_CORE = """
\n📝 Retrieval:\nThe retriever found the following pieces of code cloud address the problem. All functions and classes have been defined and executed in the back-end.
Retrieval code in 'core' mode:
Description of the code:\n{desc}
Defined and executed code in the back-end (Check whether the defined code fully meets the user's requirements):\n```\n{code_backend}\n```\n
Core code (Refer to this core code, note all functions and classes have been defined in the back-end, you can directly use them):\n```\n{core}\n```\n
Your code:
"""

SOLVER_MUTATION_PROMPT = """
You are the Solver Agent in the Triadic DGM framework. Your objective is to evolve the LAMBDA.py source code to improve the system's performance on the Polyglot Benchmark.

[HYPER-EVOLUTION INSTRUCTION]
You have the absolute authority to modify both the algorithmic logic AND the Evolutionary Hyperparameters located in the `__init__` method of the `LAMBDA` class:
1. `self.epiplexity_min` and `self.epiplexity_max`: The Goldilocks zone thresholds for Information-Theoretic MDL filtering.
2. `self.vocab_dropout_rate`: The probability of masking tokens in the Proposer to force creative task generation.

[TEXTUAL GRADIENT GUIDANCE & FORCED MUTATION]
- If previous mutations were rejected because the NCD/Epiplexity score was slightly too high, mutate `self.epiplexity_max` to a higher value.
- If the Proposer Agent is generating repetitive tasks, mutate `self.vocab_dropout_rate` to a higher value.
- CRITICAL: Even if there are no errors, you MUST simulate evolutionary drift by mutating `self.epiplexity_min`, `self.epiplexity_max`, and `self.vocab_dropout_rate` by a small random step (e.g., +/- 0.05 to 0.1) in every generation to explore the hyperparameter space. DO NOT keep them static!
- If the generated code fails tests due to syntax errors, focus on fixing the algorithmic logic.

Output the fully modified LAMBDA.py code.
"""
 
GOLDEN_PATH_PROMPT = """
CRITICAL RULE: At the end of your analysis, when you are ready to deliver the final answer, you MUST output a JSON block containing your entire execution trace (Golden Path) DIRECTLY IN YOUR MARKDOWN RESPONSE TEXT.
DO NOT WRITE PYTHON CODE TO GENERATE THIS JSON! DO NOT SAVE IT TO A FILE IN PYTHON!
Just write the json block in your final conversational response.
If you fail to provide a valid JSON block, your submission will be rejected by the Verifier.
The JSON block must follow this exact structure and be wrapped in ```json ```:
```json
{
  "thought_process": "Summary of your analytical reasoning",
  "code_executed": "The core python code you ran",
  "execution_results": "Key metrics or output from the code",
  "final_insights": "Business insights derived from the data"
}
```
"""
