"""Platform-independent question codes, validation and branching."""
import copy
import json
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).parent


class Engine:
    def __init__(self):
        self.instrument = json.loads((ROOT / 'instrument.json').read_text())
        self.questions = {}
        self.order = []
        for original in self.instrument['questions']:
            q = copy.deepcopy(original)
            qid = q['id']
            if q['type'] == 'matrix':
                for i, row in enumerate(q['rows']):
                    self.add(dict(id=f'{qid}_{i+1}',parent=qid,title=q['title']+'\n'+row,type='single',optional=True,
                                  shuffle=False,options=[dict(code=f'c{j+1}',label=c) for j,c in enumerate(q['columns'])]))
                self.add(dict(id='Q17_other',parent=qid,title='Другое решение — укажите (необязательно).',type='text',max_length=500))
                self.add(dict(id='Q17_other_frequency',parent=qid,title='Другое решение: как часто вы его использовали? Название можно не указывать; если другого решения нет, вопрос можно пропустить.',type='single',
                              shuffle=False,options=[dict(code=f'c{j+1}',label=c) for j,c in enumerate(q['columns'])]))
            elif q['type'] == 'location':
                self.add(dict(id='Q25_region',parent=qid,title=q['region_label'],type='text',max_length=200))
                self.add(dict(id='Q25_place',parent=qid,title='Тип населённого пункта',type='single',shuffle=False,
                              options=[dict(code=f'c{i+1}',label=l,other=i==6,pinned=i>=6) for i,l in enumerate(q['places'])]))
                self.add(self.text('Q25_place_other','Другой тип населённого пункта — укажите (необязательно).',500))
            else:
                self.add(q)
                if any(o.get('other') for o in q.get('options',[])):
                    self.add(self.text(qid+'_other','Другой вариант — укажите (необязательно).',500))
                if qid == 'Q29': self.add(self.text('Q29_case','Какую именно ситуацию?',300))
                if qid == 'Q26a':
                    self.add(self.text('Q26a_action','Что именно? Одно предложение (необязательно).',300))
                    self.add(dict(id='Q26a_time',title='Когда вы в последний раз смотрели свои показатели? (необязательно)',
                                  type='single',shuffle=False,options=[dict(code='c1',label='Последние 30 дней'),dict(code='c2',label='Раньше'),dict(code='c3',label='Не помню')]))
                if qid == 'Q26b': self.add(self.text('Q26b_reason','Что стало основной причиной последнего такого прекращения?',300))
                if qid == 'P03':
                    self.add(self.text('P03_purchase','Что купили? (необязательно)',300))
                    self.add(dict(id='P03_amount',title='Примерная сумма покупки, ₽ (необязательно)',type='money',options=[dict(code='unknown',label='Не могу оценить'),dict(code='refused',label='Не хочу отвечать')]))

    def text(self,qid,title,limit):
        return dict(id=qid,title=title,type='text',max_length=limit,optional=True)

    def add(self,q):
        self.questions[q['id']]=q
        self.order.append(q['id'])

    def route(self, answers, mode='core', seed=None):
        if mode not in ('core','concept','price'): raise ValueError('Unknown survey mode')
        if answers.get('S03') in ('c3','c4') or ('S03' in answers and answers['S03'] is None): return ['S03']
        result=[]
        for qid in self.order:
            q=self.questions[qid]
            if q.get('mode')=='concept' and mode=='core': continue
            if q.get('mode')=='price' and mode!='price': continue
            base=qid.split('_')[0]
            if base in [f'Q{i:02}' for i in range(9,16)] and answers.get('Q08') not in ('c2','c3','c4','c5'): continue
            if base in [f'Q{i:02}' for i in range(10,16)] and answers.get('Q09')=='c5': continue
            if base in ('Q26a','Q26b') and answers.get('Q26') not in ('c1','c2'): continue
            if qid.endswith('_other') and qid!='Q17_other':
                parent=qid[:-6]; codes=answers.get(parent)
                selected=codes if isinstance(codes,list) else [codes]
                if not any(o.get('other') and o['code'] in selected for o in self.questions[parent].get('options',[])): continue
            if qid=='Q29_case' and answers.get('Q29')!='c1': continue
            if qid=='Q26a_action' and answers.get('Q26a')!='c1': continue
            if qid=='Q26b_reason' and answers.get('Q26b')!='c1': continue
            if qid in ('P03_purchase','P03_amount') and answers.get('P03')!='c1': continue
            if qid=='Q33' and answers.get('Q32')!='c1': continue
            result.append(qid)
        if seed is not None:
            rows=[f'Q17_{i}' for i in range(1,7)]
            shuffled=rows[:]; random.Random(str(seed)+'Q17_rows').shuffle(shuffled)
            replacements=dict(zip(rows,shuffled))
            result=[replacements.get(qid,qid) for qid in result]
        return result

    def validate(self,qid,value):
        if value is None: return None
        if qid.endswith('_note'):
            if not self.questions[qid[:-5]].get('note'): raise ValueError('Пояснение недоступно')
            if not isinstance(value,str) or len(value)>500: raise ValueError('Не более 500 символов')
            return value.strip() or None
        q=self.questions[qid]
        kind=q['type']; options=q.get('options',[])
        codes={o['code'] for o in options}
        if kind=='single':
            if value not in codes: raise ValueError('Выберите ответ кнопкой')
        elif kind=='multi':
            if not isinstance(value,list) or any(v not in codes for v in value): raise ValueError('Выберите варианты кнопками')
            value=list(dict.fromkeys(value))
            if len(value)>q.get('max_choices',len(options)): raise ValueError(f'Можно выбрать не более {q["max_choices"]} вариантов')
            if len(value)>1 and any(o.get('exclusive') and o['code'] in value for o in options): raise ValueError('Этот ответ нельзя сочетать с другими')
        elif kind=='money':
            if value in ('unknown','refused'): return value
            raw=str(value).strip().replace(' ','').replace('\u00a0','').replace(',','.')
            if not re.fullmatch(r'\d{1,12}(?:\.\d{1,2})?',raw): raise ValueError('Введите неотрицательную сумму в рублях, например 0 или 1500')
            try: number=Decimal(raw)
            except InvalidOperation: raise ValueError('Некорректная сумма') from None
            return float(number) if number%1 else int(number)
        elif kind=='text':
            if not isinstance(value,str) or len(value)>q.get('max_length',500): raise ValueError(f'Не более {q.get("max_length",500)} символов')
            return value.strip() or None
        return value

    def remaining_bounds(self,answers,done,mode='core',seed=None):
        """Questions left, including current; notes are not separate steps.

        Unknown branch gates use reachable shortest/longest completions.
        Existing values (including a skipped None) are never replaced.
        """
        done=set(done)
        if 'S03' not in done:
            return (1,1)  # Eligibility is a separate, one-question check.
        gates={
            'Q08':('c1','c2'), 'Q09':('c5','c1'),
            'Q26':('c3','c1'), 'Q26a':('c2','c1'), 'Q26b':('c2','c1'),
            'Q29':('c2','c1'), 'P03':('c2','c1'), 'Q32':('c2','c1'),
        }
        counts=[]
        def in_mode(qid):
            section=self.questions[qid].get('mode')
            return not (section=='concept' and mode=='core' or section=='price' and mode!='price')
        for longest in (False,True):
            future=copy.deepcopy(answers)
            for qid,choices in gates.items():
                if qid not in future and qid not in done and in_mode(qid):
                    future[qid]=choices[int(longest)]
            for qid,q in self.questions.items():
                if qid in future or qid in done or not in_mode(qid): continue
                options=q.get('options',[])
                others=[o for o in options if o.get('other')]
                regular=[o for o in options if not o.get('other')]
                if others and regular:
                    code=(others if longest else regular)[0]['code']
                    future[qid]=[code] if q['type']=='multi' else code
            counts.append(sum(qid not in done for qid in self.route(future,mode,seed)))
        return tuple(counts)

    def options(self,qid,seed):
        q=self.questions[qid]; options=copy.deepcopy(q.get('options',[]))
        if q.get('shuffle'):
            regular=[o for o in options if not o.get('pinned')]; tail=[o for o in options if o.get('pinned')]
            random.Random(str(seed)+qid).shuffle(regular)
            return regular+tail
        return options

    def prune(self,answers,mode):
        """Remove downstream answers made ineligible by an earlier edit."""
        allowed=set(self.route(answers,mode))
        return {k:v for k,v in answers.items() if k in allowed or (k.endswith('_note') and k[:-5] in allowed)}
