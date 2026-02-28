Советую использовать conda или любой другой менеджер зависимостей, чтобы не заморачиваться конфликтами версий.
dependencies:
- numpy==1.26.4
- pandas
- sklearn
- matplotlib, plotly, dash
- umap
- tqdm
- nltk
- hdbscan
- spacy, spacy-ru_core_news_lg, en_core_web_sm, cupy (for gpu),
- pymorphy3
- gensim
- sentence-transformers
- ipywidgets
- openpyxl
- duckdb

- conda install -c conda-forge spacy spacy-ru_core_news_lg en_core_web_sm
- conda install -c conda-forge pandas numpy gensim plotly dash matplotlib nltk scikit-learn umap-learn hdbscan
- conda install -c conda-forge notebook, pymorphy3, ipywidgets