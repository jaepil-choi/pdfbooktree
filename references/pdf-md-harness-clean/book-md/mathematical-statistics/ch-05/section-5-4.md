# 5.4 모의실험을 이용한 근사

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 221-232

<!-- page 221 -->

모의실험을 이용한 근사

이 절에서는 랜덤표본의 관측값을 이용하여 통계량의 분포를 근사하거나 그 특성을 연구하는 방법을 알아보기로 한다. 특정한 분포를 따르는 확률변수의 관측값을 흔히 난수(], , random number)라고 부르고, 최근에는 이러한 난수들을 생성할 수 있는 기 능이 많은 통계패키지에 주어져 있다. 8l) 연습문제 (5.15)에 이러한 적률생성함수를 근사하는 과정이 소개되어 있다.

82) 확률밀도함수가 9(z)= dF(z)/dc로 주어지고 J(F-'(a)) > 0이면 이 조건이 만족된다.

<!-- page 222 -->

## 이러한 난수의 생성에 기본이 되는 것은 균등분포 U(0,1)에서의 관측값으로서 이

를 균등난수(1) 속 , uniform random number)라고 하며, 부록 III에서는 패키지 R에 서 균등난수를 생성하는 기능이 소개되어 있다. 또한 이러한 균등난수로부터 확률적분 변환에 관한 <정리 4.3.3>을 이용하여 임의의 분포로부터의 난수를 생성할 수 있다. 예 5.4.1 로지스틱분포에서의 난수 생성 <예 4.1.5>에서 소개된 로지스틱분포 L(0,1)의 확률밀도함수와 누적분포함수 는 각각 f(a)= (1+c), P(3)=1- (1+e:) 1812^48 로 주어진다. 이로부터 누적분포함수의 역함수는 다음과 같이 주어지는 것을 알 수 있다. F'(2)= 1081-21 따라서 <정리 4.3.3>으로부터 균등분포 U(0,1)을 따르는 확률변수 U에 대하여 2=1081-디~1(0,1)

## U

임을 알 수 있고, 이를 이용하여 로지스틱분포 L(0,1)에서의 난수를 구할 수 있다. 또한 0+4=01081- +*~L(,0) 임을 이용하여 일반적인 로지스틱분포 L(w,a)에서의 난수를 생성할 수 있다. <예 S.4.1>에서와 마찬가지로, 균등분포 U (0,1)을 따르는 확률변수 U에 대하여 -l0g(1-U) ~ Exp(1), o1-log(1-U)} ~ Exp(a) 임을 이용하여 지수분포 Exp(o) 에서의 난수를 생성할 수 있고, 표준정규분포의 누 적분포함수의 역함수 $-'(u)에 대하여

## 5'(U)~N(0,1), q8'(U)+K~N(W,02)

임을 이용하여 정규분포 N(p,o")에서의 난수를 생성할 수 있다. 이러한 방법을 이 용하여 여러 가지 분포에서의 난수를 생성하는 기능이 부록 III에 소개된 R에 패키 지화 되어 있다. 230 5장 표본분포의 근사

<!-- page 223 -->

정리 5.4.1 난수를 이용한 정적분의 근사

## 서로 독립이고 균등분포 U(0,1)을 따르는 V1,

•··, U,,과 구간 (a,6]에서 연속인 함수 g (z)에 대하여 다음이 성립한다. X;=(6-0)U,+a~U(0,6)(i= 1,,") plim 72->00 670Lg(3)=Igla)dar

## [증명] X 1, •, X,이 서로 독립이고 확률밀도함수가

pax, (2)= 6-a , 1(0.0) (a) 로 주어지는 균등분포 U(a, 6)를 따르고 로 주어진다. 따라서 대수의 법칙으로부터 plim 6-429(X)=(0-0)Elg(X,)=/ 9(2)dz <정리 5.4.1>에서의 확률수렴을 이용하여 정적분의 근사값을 구하는 방법을 몬테칼 로적분(Monte Carlo integration)이라고 한다. 즉 서로 독립적으로 생성된 균등난수 ., ?,.을 이용하여 y:=(6-a)g((6-0)u;ta)(i= 1,,7) 1g(a)d= ¼ 20 m00 " ";=1 와 같이 정적분의 근사값을 구하는 방법을 몬테칼로적분이라고 한다. 이는 Y;=(6-a)9((6-a)U,+a)(&= 1,,2) 의 관측값을 이용하여 E(Y, )에 대한 추측을 하는 것이므로 B(Y,)에 대한 점근신 뢰구간으로 이러한 근사의 정밀도를 나타낼 수 있다.

<!-- page 224 -->

예 5.4.2 적분 공식을 이용하면 정적분 120z의 값이 2613임은 잘 알고 있다. 한편 독립적으로 생성된 U(0,1)에서의 난수 21, ···, u,에 대하여 2,= 20:+1, 3:=20, (i=1,0,70) 이라고 하여 ";=1 ni=1 와 같이 정적분의 근사값을 구할 수 있다. R 패키지를 이용하여 생성된 난수들을 이용하여 이 정적분의 근사값과 95% 점 근신뢰구간을 구해보면 다음과 같이 주어진다. 이 결과에서 볼 수 있듯이 난수의 개수 n이 커질수록 이러한 근사의 정밀도가 좋아진다. 표 5.4.1 몬테칼로적분에 의한 정적분 t2da (= 8.666…•)의 근사값과 95% 오차한계 10000

## Y

8.7612 8.5633 8.6515 100000 8.6473 j- 1.968,/Vm 7.8241 8.2728 8.5604 8.6185 j)+1.965/Vm 9.6983 8.8538 8.7426 8.6762 예 5.4.3 로지스틱분포의 분산 로지스틱분포 L (0,1)은 2= 0에 관해 대칭인 분포로서 그 분산은83) -∞ 임이 알려져 있다. 한편 <예 5.4.1>로부터 균등분포 U(0,1)을 따르는 확률변

## 수 U에 대하여

×= 1081-디~L(0,1)

## U

## 83) 부분적분을 이용하고 무한급수로 나타내어 적분하면

•to et -∞ (1+er): d2=4) 얻을 수 있다. 한편 후리에급수를 이용한 다음의 항등식에서 2= 0을 대입하면 위의 무한급수의 값을 8=0월+42 Ch) cos(na) (-aKaKa) 232 5장 표본분포의 근사

<!-- page 225 -->

## 따라서 독립적으로 생성된 U (0,1)에서의 난수 21, •, 2,에 대하여

2:= 1081-0: Whi , Y:= 2를 (i= 1,0,7) 이라고 하여 다음과 같이 로지스틱분포 L(0,1)의 분산의 근사값을 구할 수 있다. 2? R 패키지를 이용하여 생성된 난수들을 이용하여 이 정적분의 근사값과 95% 점 근신뢰구간을 구해보면 다음과 같이 주어진다. 표 5.4.2 로지스틱분포 L (0,1) 의 분산 72/3(=3.289••·)의 근사값과 95% 오차한계 " 10000 100000 2.9775 3.3375 3.3201 3.2949 j- 1.9653/vm 2.0043 2.9799 3.2034 3.2584 j+1.965g/vm 3.9506 3.6951 3.4369 3.3313 예 5.4.4 표본비율의 극한분포 모비율이 pp(0<p< 1)인 베르누이시행을 독립적으로 7번 관측한 결과를 X1, •·, Xn이라고 할 때, 대수의 법칙과 중심극한정리로부터 표본비율 p,= (X」 +…+X,)/n에 대하여 다음이 성립하는 것을 알고 있다. plim pn=p, ph-p 72->∞ Vp(1-p)/72 2-78 > Z, 2~N(0,1) 따라서 슬럿츠키의 정리와 <정리 5.3.2>로부터 ph-p -> Z,

## Z~N(0,1)이므로

## VP, (1-P,)/7 7-00

limP 2a12 S Ph-p S 2ial2 =1-a : limP(p,-ea/VD,(1-pa)ln Sps p,tza/2Vp,(1-7.)/m}=1-2 이로부터 모비율 pp에 관한 100(1-a)% 점근(F:, asymptotic)신뢰구간을 다음 과 같이 나타낼 수 있다. pE lp- 2a/ VP(1-p)/n, Pht za V2,(1-Da)/n ]

<!-- page 226 -->

예 5.4.5 표본비율의 극한분포를 이용한 원주율 "의 근사

## 서로 독립이고 균등분포 U(0,1)을 따르

그림 5.4.1 랜덤하게 떨어뜨린 점들 는 두 확률변수 Ul, U2에 대하여 이들을 (uil, 2iz)

## 좌표로 하는 점 (U,U2)을 관측한다는

× × 것은 각 변의 길이가 1인 정사각형 내에 × 한 점을 랜덤하게 떨어뜨리는 것으로 생각 × 할 수 있다. 이 실험에서 떨어뜨린 점이 × 사원 내에 떨어질 확률은 × × P(U:+U3≤1)=7/4 이제 이러한 실험을 독립적으로 반복하여 랜덤하게 떨어뜨린 점들이 사원 내에 떨어지는 상대도수가 이 사건의 확률 7/ 4에 가까워진다는 것이 대수의 법칙의 뜻이다. 따라서 독립적으로 생성된 U(0,1)에서의 난수 211:212;2m1) 2m2에 대하여 2,=uh+u% (i=1,,7) 이라고 하면 표본비율의 관측값 72i=1 은 확률 p=P(U)+U3 ≤ 1)=/4의 근사값이며 4p,을 4p=ㅠ의 근사값으 로 사용할 수 있다. 또한 <예 5.4.4>로부터 4p에 관한 점근신뢰구간으로 근사의

## 정밀도를 나타낼 수 있다. R 패키지를 이용하여 생성된 난수들을 이용하여

4p=의 근사값과 95% 점근신뢰구간을 구해보면 다음과 같이 주어진다. 표 5.4.3 4p=ㅠ(=3.14159·•)의 근사값과 95% 오차한계 " 10000 100000 3.3600 3.1320 3.1344 3.1452 47,-4X1.96 vp(1-p.)/n 3.0755 3.0308 3.1024 31351 4p,+4X 1.96 vp (1-p.)/n 3.6445 3.2331 3.1664 3.1552 234 5장 표본분포의 근사

<!-- page 227 -->

일원분류모형 다변량 정규분포 신퇴집입 지환 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확률석푼번환 중심극한정리 표본회귀계수 단순 설명변수 점근 대수의 법칙 표본적률 극한분포 점근분포 평균오차 난수 첨예도 균등난수 표본상관계수 분위수 분산안정변환 표본분위수 가능도 추정법 추정 추정량 몬테칼로적분 다중모수 지수족 점수함수 연습문제 가능도방정식 일지성 가능도 함수 적률이용추정량 쿨백-라이블러 괴리도 순오복함수 공간 확률측도 정사영 조건부확률 공리 최소제곱 추정법 확률 . 최소제곱 추정량 점근정규성 표본공간 확률밀도함수 랜덤한 실험 확률변수 사전 가산가법성 이산형 사후 독립 1표함수 펵규 기댓감 연속형 표주편차 이상 확률분포 확률질량함수 표주화

## 5.1 확률변수 X가 자유도 32인 카이제곱분포 x2(32)를 따를 때 중심극한정리를

이용하여 확률 P(20<X< 40)의 근사값을 구하고, R을 이용하여 구한 값 과 비교하여라.

## 5.2 확률변수 X가 포아송분포 Poisson (25)를 따를 때 중심극한정리를 이용하

## 여 다음 확률의 근사값을 구하고, R을 이용하여 구한 값과 비교하여라.

## (a) P(19 CX S 33)

(b) P(19.5<X < 33.5)

## 5.3 확률밀도함수가

J(3;0)=e-(-9)1(0,+o)(z) (0는 실수) 인 모집단으로부터의 랜덤표본 X1, , X, 에 대하여 Y,=, min X, 이라 고 할 때 plimy,,= 8 임을 밝혀라. 5.4 베타분포 Beta(1,a)로부터의 랜덤표본 X1,·,X,,에 대하여 Y,,=, max Xi 이라고 할 때 n'/a(1-Y,,)의 극한분포를 구하여라.

## 5.5 확률밀도함수가

f(z)= 02-0-'11,8)(z) 인 모집단으로부터의 랜덤표본 X,,•·,X,에 대하여 Y,=, max X, 이라 고 할 때 1/aY,,의 극한분포를 구하여라. 5.6 표준지수분포 Exp(1)로부터의 랜덤표본 X1;··,X,,에 대하여 Yn=, max Xi 이라고 할 때 Y,,- 10g%의 극한분포를 구하여라.

<!-- page 228 -->

5.7 베타분포 Beta(a, 1)(a> 0)로부터의 랜덤표본 X1, ,X,에 대하여 Y,= ISisn mIn A;이라고 할 때 D'Y,,(>0)의 극한분포가 존재하기 위한 7의 값 을 구하고, 그 극한분포를 구하여라.

## 5.8 균등분포 U(0,1)로부터의 랜덤표본 U1, ··, U,,에 대하여

ISisn 이라고 할 때 다음에 답하여라. (a) plim (Xm, Y,,)'= (0,1)'임을 밝혀라. (o) p(1-Rn)의 극한분포를 구하여라.

## 5.9 확률변수 X, 과 2에 대하여

d

## 이고, Z의 누적분포함수가 모든 실수에서 연속인 함수일 때 다음이 성립함

을 밝혀라. 84) lim SupIP(X,S2)-P(Z≤2)|=0 5.10_ 확률변수의 열 X,, (p=1,2,…)에 대하여 2SWPP(X.12K)=0 k-×∞ 이 성립하면 X, (p= 1,2,…)이 확률적으로 유계(bounded in probability)라 고 하고 기호로는 X,= 0p(1), 72-200 로 나타낸다. 한편 Dlim Z,,= 0인 Z,(”=1,2,…)에 대하여는 Z,,= 0p(1), 72-200 와 같이 나타낸다. 이제 An= Op(1), 1n=Op(1): Zn=op(1), 7200 일 때 다음이 성립함을 밝혀라.

84) 이러한 균등수렴의 결과로부터 P(X,S 2n)=P(ZS 2n)과 같이 7에 의존하는 값 2,

까지의 누적확률의 근사계산이 가능한 것이다. 236 5장 표본분포의 근사

<!-- page 229 -->

(a) X,+Y,,=Op(1), 70200 (b) X,,Y,=Op(1), 7200 (c) Znx,= Op (1), 7-200 (d) 2,= 0p (1), 72-200

## 5.11 확률변수 X, 과 Z의 누적분포함수가 모든 실수에서 연속인 경우에

d n->ㆀ 이면 2,,= 0p (1) 72 2∞ 임을 밝혀라.

## 5.12 포아송분포 Poisson (A)로부터의 랜덤표본 X1,•••,X,, 을 이용한 표본평균

2,에 대하여 vig(8.)-9) 2 2.2~20.1) 가 성립하는 분산안정변환 9를 구하고, 이 결과를 이용하여 1에 관한 점근 신뢰구간을 구하는 방법을 설명하여라.

## 5.13 베르누이분포 Bernoulli(p)로부터의 랜덤표본 X1, , X,을 이용한 표

본비율 pn= L5X./n에 대하여 vn(g(p,)-9(p) - Z, 2~N(0,1) 가 성립하는 분산안정변환 9를 구하고, 이 결과를 이용하여 pp에 관한 점근 신뢰구간을 구하는 방법을 설명하여라. 5.14 서로 독립이고 성공률이 p(0<p< 1)인 베르누이시행 X 1,••,,,•••에서

## " 번째 성공까지의 시행횟수를 W, 이라고 할 때

P,=r/W, 에 대한 다음 질문에 답하여라. (a) r이 한없이 커질 때 VT(pr-p)의 극한분포를 구하여라. (b) r이 한없이 커질 때 vi((2)-9(0) 1 7-280

## 1N(0,1)

<!-- page 230 -->

이 성립하는 분산안정변환 9를 구하고, 이 결과를 이용하여 x이 클 때 p에 관한 95% 근사신뢰구간을 구하는 방법을 설명하여라. 5.15 <예 5.3.8~에서 표본분위수의 극한분포를 구하는 과정에서 "-;,+i2: 2~BXp(1)(=1,0) W,= vn -1,- (-10g(1-a)) val(1-a) 으로 정의된 확률변수들에 대하여 다음이 성립함을 설명하여라. (a) 1, 의 누율생성함수 cgfy (s)에 대하여 cgfy, (5),200-s10g(1-a)+ 2n 1-a (b) Wn의 누울생성함수 Cgjw. (t)에 대하여 cgw(t)=cs.(vit/va/(1-a))+ vitlog(1-0)/va/(1-a) (C) cgiw.(6),.. "~∞ 2

## 5.16 예 5.3.82에서와 같은 가정하에서 11,200

oa", snm-00 ~ 3n(0<aKB<1) 인 경우에 표본분위수 X(.)과 X(on)의 결합분포에 대한 극한분포를 유도 하고, 이로부터 표본 사분위수범위인 ~ 3n/4) 의 극한분포를 유도하여라.

## 5.17 확률밀도함수가

f(w;f;o)= o (1te-6-nyop 1-0,te)(t) e-(e-m)/0 인 로지스틱분포 L(0),-0CM<+∞,0≥0 모형에서의 랜덤표본 X ,,,X, (n≥ 2)에 기초한 표본사분위수 X (n/4), X (In/2), X (137/4)) 들로부터 정의되는 다음과 같은 통계량들을 이용하여 1, o에 대한 추론을 하려고한다. Pr=X(ml2), 0m= (X(130/4) -X(m/a)/ (210g3) 238 5장 표본분포의 근사

<!-- page 231 -->

표본 크기 n이 한없이 커질 때 ViM-쓰 스의 극한분포를 구하고, 이 결과

## 를 이용하여 A에 관한 95% 근사신뢰구간을 구하는 방법을 설명하여라.

## 5.18 확률밀도함수가

J(a:;:0)= , rel-Al010.401(2),-0<NCt 00,020 인 이중지수분포 DE(,a) 모형에서의 랜덤표본 X 1,•·,X,, (m≥ 2)에 기초한 표본중앙값과 표본평균절대편차(mean absolute deviation)를 각각 nE=1 이라고 하자. (a) on) -> o 임을 밝혀라.

## P

"- 00 (6) 표본 크기 72이 한없이 커질 때 Vm A,-쓰의 극한분포를 구하고, 이 결 과를 이용하여 µ에 관한 95% 근사신뢰구간을 구하는 방법을 설명하여라.

<!-- page 232 -->

orobability density function) 연속형 (3288 continuous type eriment) 확률변수(68주: random variable) 이산형(98w discrete type) 확률질량함수(Ht 후 1 EN 98 probability mass fuction) 확률밀도함수(HE 3182) or function) 평균(푸 mean) 기댓값(1》값 expected value) ) 이상(Wt improper) 확률분포(1)유715 probability distribution) 지표함수(1급제 9) 7적: cumulative distribution function) 표준지수분포(##)hti standard exponential distribution) 급수(류: power series) 확률생 표준편차(19 4m standard deviation) 표준화(13ft standardized) 누적분포함수 제주소: probability generating function) 적률생성함수(#*또 moment generating function) 적률(187 moment) 누율생성하 1ney cumulant generating function) 누율(※ cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분 (iterated integra) 합적률생성함수(joint moment generating function) 결합누울생성함수(joint cumulant generating function) 합누율 (joint r A joint) 주변(H)g marginal) 공분산(#4 covariance) 상관계수(68 correlation coefficient) 결합적률(1삼 joint mor (t) 조건부(19fW conditional) 조건부평균 nal variance) 회귀함수(미l regression (conditional mean) 조건부기댓값(conditional expected value) 조건부분산 1 vector) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 function) 평균제곱예측오차(mean squared prediction error) 행 gative definite) 기울기벡터(gradient vector) 2집단분포(## 189 f population distribution) 비복원추출(sampling without replace 헤시안행렬(Hessian matrix) 모집단(* popul) 단순랜덤추출(#※랜덤Itt simple random sampling) 랜덤표본(randorn sampl ribution) 복원추출(QitH sam 율(Bltf population proportion) 초기하분포(1%th hypergeome AT binomial distribution) 대의적 정의(11) 2족 repr 1g with replacement) 이항분 on) 다항계수(SIE%w multinomial coefficie ional definition 다항분포(319f th multinomial di 분포(fAtT geometric distribution) ution) 음이항전개식(negative 1A t negative binomia 송 과정(Poisson process) al expansion) 포아송 (Poiss arity) 독립증분성 (indepe occurrence rate) 정상성 5y) 희귀성(rareness) 지수분 ncrement) 비례성(propo mential distribution) 감마분 추정 ape parameter) 척도모수(F19 1울 9) ma distribution) 형상모수(HATX arameter) 표준정규분포(1 공간(HTml parameter space) 통계량(Bt:1 m sta normal distribution) 분위수(upper quanti [본비율 (1 mean) 표본분산(A sample variance) 순서통계량 JEFa Ati sample proportion) 표본평균(뉴스프가 1g distribution) 위치모수(418 9 ocation parameter) 척도모수(RIEf scale (statistics) 표본중앙값(*/야½값 sample medi an) 표본분포(유)M 4분포(Eash triangular distribution) 야코비안(Jacobian) 자유도(Eart degrees of freedoi. ter) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(¥ath uniform distribus 원분류모형 급분포(chi-squared distribution) 신뢰수준(1등)kt confidence level) 신뢰구간(1룸# confidence 규슈#빛 one way classification model) 신뢰집합( tion) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포 probability integral transformation) 다변량 정규분포(2% ERAM multivariate non 꽃습 confidence set) 치환(mt& per. 값(포효값 characteristic value) 선형회귀모형 inear regression model) 설명변수(explanatory variable) 반응변수, 30e F8ah nonsingular multivariate normal distriz riable) 계수(11g rank) 회귀계수(미용) 1곱합(Tk)※※제곱합 mean squared error sum of squares) 중심극한정리(PL A로 central limit theorem) 극한분포(KseAth limith s w regression coefficient) 표본회귀계수(sample regression coefficient) 단순(Bwt simple) d

3) 표본분위수(AA(1 sample quantile) 슬럿츠키(Slutsky) 점근(fii asymptotic) 첨예도(4t kurtosis) 표본상관계수(119분 6F g Sample

tion) 점근분포(wiiiA t asymptotic distribution) 대수의 법칙(*의 초Rl law of large numbers) 표본적률(sample moment) 분위수(4) 1분 ion coefficient) 분산안정변환(SWTR variance syabilizing transformation) 난수(aw random number) 균등난수(K)쪽 2, 1q uniform randon) nator) 일치성 r) 몬테칼로적분(Monte Carlo integration) 적률이용추정량(RRHIFIFTW method of moments estimator(MME)) 추정 (11T estimation) 추정량(1) on) 가능도방정식(피###i Ikekihood equation) 순오목함수(strictly concave function) 경계(19 boundary) 다중모수 지수족(3호 9향 1g 1k multi tt consistency) 가능도 함수(m] BETE awk likelihood function) 우도(X) 최대가능도 추정법(XaltS HT;t maximum likelihood e er exponential family of pdf's) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 점근정규성(WfiT.iERit asymptotic normality) 점수함수(score functio endicular projection) 공리(21 axiom) 표본공간(1 32i sample space) 확률(mw probability) 가산가법성(countable additivity) 확률측도 (8일 후 , probe ite information number) 최소제곱 추정법(least souares estimation) 최소제곱 추정량 least squares estimator) 열벡터 공간(column space) 정사영 (교 asure) 조건부확률(161TB ep conditional probability) 사전(1m prior) 사후(폴(& posterior) 독립(배고 한 실험(random experiment) 확률변수(1월 5g random variable) 이산형 (17 discrete type) 확률질량함수(제 3P 로 5 9 probability mass fuction) 률밀도 mutually independent) 종속(ttAl mutually depende function) 평균(41g mean) 기댓값(171값 expected value) 표준편차(1 standard deviation) 표준화(1fft, standardized) 누적분포함수(985) 4T 15g probability density function) 연속형(표 continuous type) 이상( improper) 확률분포(Besti probability distribution) 지표함수(12) 봉 distribution function) 표준지수분포 unction) 적률생성함수(Ft ht moment generating function) 적률(1 moment) 누율생성함수(Wwt.twilt cumulant generating function) 누율 (부 #*Ewa th standard exponential distribution) 멱급수(3% ws power series) 확률생성함수(14.itl probability g int) 이변량(bivariate) 확률벡터(random vector ion coefficient) 결합적률(#습 joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur 반복적분(iterated integral) 결합(joint) 주변 (E38 marginal) 공분산(#5w covariance) 상관계수(AGSEAK) 구율 joint cumulant) 조건부(1%ftst conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional varian (BBhaIl regression function) 평균제곱예측오차(mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산: 1(variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(B#1 population) 모집단 로비율(BH;¥ population proportion) 초기하분포(1w hypergeometric distribution) 복원추출(19T.Htt sampling with replacement) 이항분포 AT population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(&랜덤htt simple random sampling) 랜덤표본(random icient) 기하분포(*피A fi geometric distribution) 음이항분포(14-) sinomial distribution) 대의적 정의 (1Cm) Ti representational definition 다항분포(※At multinomial distribution) 다항계수(350688 muitinor 송(Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성(proportiona it t negative binomial distribution) 음이항전개식(negative binomial expan 준정규분포(¾2 TEREAth standard normal distribution) 분위수(upper quantile) 모수공간(1822ml parameter space) 통계량(3651m statist) areness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(HWA) 8 shape parameter) 척도모수(FI 88 scale pa At보가 samole medi Ht sample proportion) 표본평균(wKwls sample mean) 표본분산(☆#: sample variance) 순서통계량(ETM an) 표본분포(배*At sarnpling distribution) 위치모수(61me w location parameter) 척도모수(FE A 및 -• order statistic lacobian) 자유도(Etit degrees of freedom) 카이제곱분포(chisquared distribution) 신뢰수준(금* confidence level) 신뢰 ter) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(1945M uniform distribution) 삼각분포(=eft trianqular distributic t confidence interval) 일원분류모형(-TA one way classification model) 신뢰집합(1) confidence set) 치환 ion) 정칙행렬(nons ingular matrix) 정 다변량 정규분포(HE 성분 iENAti nonsingular multivariate normal distrit tion) 확률적분변환(표&유정 probability integral transformation) 다변량 정규분포(3m iENsth multivariate norn sponse variable) 계수(금1: rank) 회귀계수(Be6f8y regression coefficient) 표본회귀계수(sample regression co 값(B값 characteristic value) 선형회귀모형(#미로 linear regression model) 설명변수(explanatory variable ntral limit theorem) 극한분포(weAth limiting distribution) 점근분포(Wiiiifth asymptotic distributior 단순(wwt simple) 평균오차제곱합(주19점)#제급합 mean squared error sum of squares) 중심극한정리(Pi)) 71분 sample quantile) 슬럿츠키(Slutsky) 근(Wfir asymptotic) 첨예도(4695 kurtosis) 표본상 법칙(*※의 Rl law of large numbers) 표본적률(sample moment) 분위수(5tw quantile) 표본분이 inn hnotfiniony 브사아저한(수활동
