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
            self.questions[q['id']] = q
            self.order.append(q['id'])

    def route(self, answers, mode='core', seed=None):
        if mode != 'core': raise ValueError('Unknown survey mode')
        if 'S03' in answers and answers['S03'] not in ('c1','c2'): return ['S03']
        result=[]
        for qid in self.order:
            if qid in ('Q09','Q11','Q12','Q13','Q15') and answers.get('Q08') not in ('c2','c3','c4','c5'): continue
            if qid in ('Q11','Q12','Q13','Q15') and answers.get('Q09') not in ('c1','c2','c3','c4'): continue
            if qid=='Q33' and answers.get('Q32')!='c1': continue
            result.append(qid)
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
        gates={'Q08':('c1','c2'), 'Q09':('c5','c1'), 'Q32':('c2','c1')}
        counts=[]
        for longest in (False,True):
            future=copy.deepcopy(answers)
            for qid,choices in gates.items():
                if qid not in future and qid not in done:
                    future[qid]=choices[int(longest)]
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
