Советую использовать conda или любой другой менеджер зависимостей, чтобы не заморачиваться конфликтами версий.
dependencies:
- numpy==1.26.4
- pandas
- sklearn
- matplotlib
- plotly
- umap
- tqdm
- nltk
- gensim
- hdbscan
- sentence transformers
- spacy, spacy-ru_core_news_lg, en_core_web_sm, cupy (for gpu),
- pymorphy3
- gensim
- sentence-transformers

conda install -c conda-forge spacy
conda install -c conda-forge pandas numpy gensim plotly matplotlib nltk scikit-learn umap-learn hdbscan
conda install -c conda-forge notebook
conda install -c conda-forge pymorphy3
