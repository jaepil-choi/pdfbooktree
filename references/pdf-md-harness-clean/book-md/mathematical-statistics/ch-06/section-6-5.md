# 6.5 최소재곱 추정법

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 275-285

<!-- page 275 -->

## 6.5 최소제곱 추정법

변수 사이의 함수관계 조사를 목적으로 할 때 가장 기본적으로 사용되는 모형인 다음의 선형회귀모형에서 모수의 추정에 사용되는 최소제곱 추정법(east Squares estimation)에 대하여 알아보자. 선형회귀모형: 〈E(e;)=0, Var(e)=0,i=1,7, Cor(ene,)=0(i=j) Y:=I08o+3ib, tiottiphote 18<B,<+8, 3=0,1,P, 0<aC+8

## 이러한 선형회귀모형에서는 반응변수인 Y의 평균이 설명변수의 선형함수라는 가

정하에서 평균 반응의 추정을 하는 것이 목적이다. 따라서 가정된 선형함수 중에서 관 측값들과의 거리의 제곱을 최소로 하는 것을 찾아 추측에 사용하자는 것이 최소제곱 추정법이다. 즉 i=1 1(Y,-(2080+215,++3m8,)12 을 최소로 하는 B=(Do,B, 6,)을 찾아 설명변수가 (1) 2011,21)일 때 평균 반응을 로 추정하는 것이 최소제곱 추정법이다. 선형회귀모형에서의 최소제곱 추정: 오차의 제곱합인 을 최소로 하는 BkS= (865 i=1 65)을 회귀계수 B=(Pow8, 8)'의 최소제급 추정량(least squares estimator)이라고 하며, 평균반응 1(20,81:3,)=E(Ylo0180) 의 최소제곱 추정량은 다음과 같이 정의한다. 이러한 선형회귀모형을 벡터와 행렬을 사용하여 나타내기 위하여

<!-- page 276 -->

라고 하면 선형회귀모형과 최소제곱 추정량을 다음과 같이 간략하게 나타낼 수 있 다.105) 벡터와 행렬을 이용한 선형회귀모형과 최소제곱 추정량: (Y= Xgte 〈E(e)=0, Var(e)=aT, LGER”+, 0≥ 0, rank(X)=p+1 85= argmin ||y-X3 12, IY-X35S 12= min. y-X3112

## BERP+1

정리 6.5.1 선형회귀모형에서의 최소제곱 추정 (a) II= X(X(X)- 1X'라고 하면 106) II'=I, I(I-I)=0, IIX=X (6) IIy- 23|2= III(Y-xg) 12+ 1(1-MI)Y 12 KBSE=ITY, BISE=(XX)-181Y [증명] (a) 전치행렬과 역행렬의 성질로부터 D'=(x5)((XX) 1)H=XXX) II= II 7'(I-I)=X(XX) 1X1-X(XCX) 1X) =X(XX) r-X(MX))X=0 (b) IIX= X 이므로 Y-X3=II(Y-X3)+(I-I)Y :: IIY- 23|2=||T(Y-Xg) 12+ 1 (1-II)Y 12+2(I(Y- Xg)'(I-II)Y

## 105) 여기에서 rank(X)는 행렬 X의 계수(rank)를 뜻하고, argmin II Y- X3 || 2에서 argmin

은 'argument of minimizing'의 약자이다.

## BERP+T

## 106) 선형회귀모형의 가정에서 행렬 X가 nX (p+1)의 행렬로서 그 계수가 p+1이므로

XX의 여행렬이 존재하고, 행렬 II=X(X'X)-X'를 X의 열벡터공간(column space)으 로의 정사영(TED볶, orthogonal projection)이라고 한다. 286 6장 추정

<!-- page 277 -->

그런데 II'(I- II) = 0이므로 Iy-2312=II(Y-X3) 12+11-D)Y 12 여기에서 IF(X-83) 12=IIY-X312=1X(XX)-X'y-X312 이므로 선형회귀모형에서 오차항 분산의 추정량으로는 다음의 평균오차제곱합을 사용한다. 2=Iy-X865512/(m-p-1) 정리 6.5.2 최소제곱 추정량의 성질 선형회귀모형 E(e)= 0, Var(e)= 021,, (BERP+1, 02> 0, rank(X)=p+1 에서 다음이 성립한다. (a) B(BSE)=B, Var((SE)=02(X'X)-1

6) E(2)=02

(c) 추가적으로 오차항의 분포가 정규분포라면, 즉 e~ N,,(0, 02T) 라면 BSE~N(3,02(XX)-1), (n-p-1)82102~x2(n-p-1)

## 이고 34SE과 2은 서로 독립이다.

[증명] (a) BkSt=(Xx)- 1Xly이고 E(Y)= XB, Var(Y)= 03, 이므로 B(3SE)=(XX)-IXE(Y)=(88)-18683=8 var(alse)=(xlx) xlvar(8)((268)-185)=0(268)1 (b) <정리 6.5.1>의 (b)로부터 2= ly-xg(s512/(n-p-1)= 1(1-M)Y 12/(n-p-1) 또한 <정리 6.5.1>의 (a)로부터

<!-- page 278 -->

(1-II) XB=0, (I-II)Y=(I-II)(Y - Xg) = (I- I)e 1 (1-m)e 12=e'(1-m)'(1-m)e=e'(1-n)e 8= 1(I-H)(Y-XB) 12/(n-p-1)=e'(1-I)e/(7-p-1) 그런데 e'(I-II)e = trace(e'(I-II)e)= trace((1-II)ee')이므로 (n-p-1)E(0)=Ele'(I-n)el =Eltrace(1-n)ee')|=trace(1-n)Eleer]) :: (n-p-1)E(8)= trace((1-n)var(e)= 0trace(1-n) 한편 trace (A+B)= trace (A)+ trace(B), trace(AB)=trace (BA)이므로 trace(1,-X(XX)-'X)=n-trace((Xx)-1x6x) =n-trace(tp+1)=n-p-1 :: B(o)=Otrace(In-E)/(7-p-1)=02 (c)의 증명은 4장의 정리 4.4.6~에 주어져 있다.

## 선형회귀모형에서 설명변수의 값들로 주어진 행렬 X의 열들이 서로 직교하면

※'X가 대각행렬이 되어 계산이 쉬울 뿐만 아니라 변수 사이의 관계에 대한 해석도 용이하다. 한편 행렬 X의 열들이 서로 직교하지 않는 경우에는 이들을 직교하는 행렬 로 변형하여 최소제곱 추정을 비롯한 추론을 하면 편리하다. 설명변수의 n X (p+ 1) 행렬 X에 대하여 rark(X)= p+1일 때 X=(20,21), 2o:nXpo:A:nXp (potpi=p+1) D=X(XX) XB=(868) 라고 하면 평균반응을 다음과 같이 나타낼 수 있다. XB=XoBo+X.B,=Xo(Bo+(x8x0)-x6213)+(I-D)X8. 즉 210= (1-Io)X, 이라고 하면, X10의 열은 Xo의 열과 직교하고 평균반응을 X8=2080+818,=2070+X108,.70=5+(8620)-)868.81 과 같이 나타낼 수 있으므로 설명변수의 행렬 X=(Xo.kr)을 (Xo, Xio)로 대신하여 선형회귀모형을 나타낼 수 있다. 따라서 이와 같이 직교하는 (Xo, Xilo)를 이용하여 에 대하여 다음이 성립하는 것을 알 수 있다. Ho.1= Io+ I10: 16110= 0 288 6장 추정

<!-- page 279 -->

즉 정사영 행렬 ILo.1을 서로 직교하는 두 정사영 행렬의 합으로 분해할 수 있는 것 이다. 이와 같은 정사영 행렬의 분해를 이용하면 다음 정리가 성립하는 것을 알 수 있다. 정리 6.5.3 설명변수의 직교화와 최소제곱 추정 <정리 6.5.2>의 선형회귀모형에서 X=(X:x), 5o:nxpo:h:nXp (Dotp=p+1) To=20(X26) X6, X10=(1-E)X, 0l0 = Xio(sio Rio) ' Xio 라고 하면 다음이 성립한다. (a) KBSE= 206,65+ 115,656= 207065E+ 2108,450 5675= 10Y, 2108,555=11101

## BSE-70658-(8850)-8656,556

(b) corlifse 16,4S5)=0 B(iSE)=7, Var(6655)=2(8620)1 B(B(55)= B,, Var(ase)= 2(riorio)1 예 6.5.1 절편이 포함된 선형회귀모형 선형회귀모형에서 평균반응이 B(Y:ltitatip)=B,+B2a t.+8,2m(i=1,,7) 로 가정된 경우에 2j= (21, +·+2nj)/n(j= 1,p)라고 하면 평균반응을 Bo+Bint:+B,im=%+8,(n-21)++8,(p-2p) 로 나타낼 수 있다. 이 경우에 5o=(11), 20=(1-21100i-2p)15i5p 이므로 라고 하면

<!-- page 280 -->

2102l0 =(Sx), XioY=(5,x) 임을 알 수 있다. 따라서 최소제곱 추정량은 다음과 같이 주어진다. (Si… Sip)

## (B1

70=y, (Siy 5p1. Spp 290 6장 추정

<!-- page 281 -->

다변량 정규분포 ㄴㆉㅂㅂ 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정식 다변량 정규분포 확률식권연환 점근 대수의 법칙 중심극한정리 표본회귀계수 단순 설명변수 표본적률 극한분포 점근분포 평균오차지 난수 첨예도 균둥난수 표본상관계수 분위수 분산안정변환 표본분위수 가능도 추정법 추정 추정량 일치성 몬테칼로적분 가능도 함수 적률이용추정량 다중모수 지수족 점수함수 연습문제 가능도방정식 쿨백-라이블러 괴리도 순오목함수 확률측도 정사영 조건부확률 공리 최소제곱 추정법 홬률 최소제곱 추정량 점근정규성 표본공간 표함수 확률밀도함수 랜덤한 실험 확률변수 사전 사후 독립 가산가법성 기댓값 연속형 이산형 표주평차 이상 확률분포 확률질량함수 표주화 6.1 모평균이 A, 모표준편차가 o(o> 0)인 모집단 분포에서의 랜덤표본을 X... 이라고 할 때 모집단 분포의 왜도 7=B(4.4))와 첨에 도 n=미(주)-3의 적물이용주정량을 구하여라.

## 6.2 다음 각 모형에서의 랜덤표본을 Al, ., X,,이라고 할 때, 각 경우에 a, 3

의 적률이용추정량을 구하여라. (a) Gamma(a,2), a> 0 (b) Gamma(2,3), 8>0 (C) Gamma(a,3), a>0, B>0

## 6.3 확률밀도함수가

J(t;a)=az"-'exp(-20)10.+∞)(z) 인 와이불분포 Weibull(a,1), a≥ 0 모형에서의 랜덤표본을 X 1, ., X,, 이라고 할 때 Ba(0gx,)=/ (10gz)e dla=- 0.57710 임 107)을 밝히고, 이로부터 10gX 1: , 10g%,, 을 이용한 a의 적률이용주정 량을 구하여라.

## 6.4 확률밀도함수가 다음과 같이 주어지는 각 모형에서의 랜덤표본을 X I, •••,

An이라고 할 때, 각 경우에 0의 적률이용주정량과 최대가능도 추정량을 구 하여라. (a) J(a;0)=(32202)1o.o1(z),020 (6) 9(a;0)=2022-810.+0)(2),020

107) 로그갈마함수의 일차도함수를 1(a)= 8a 1ogN(a)라고 하면 !..

(logz)e-2dz=W(1) 임을 알 수 있으며, w(a)는 다이감마(digamma)함수라고 불리우며 패키지 R을 이용하여 그 값을 계산할 수 있다.

<!-- page 282 -->

## 6.5 다음 각 모형에서의 랜덤표본을 21, , X,, 이라고 할 때, 각 경우에 0의

최대가능도 추정량과 그 극한분포를 구하여라. (a)의 경우에는 그 극한분포 의 분산과 적률이용추정량 극한분포의 분산을 비교하여라. (a) Beta(0,1), 0> 0 (b) Pareto(1,0), 0≥ 2

## 6.6 다음 각 모형에서의 랜덤표본을 X 1, •·, X,, 이라고 할 때, 각 경우에

7=Po(X,> a) (Q는 주어진 양수) 의 최대가능도 추정량을 구하여라. (a) Exp(0), 0> 0 (b) Pareto(1,0), 0> 0 6.7 기하분포 Geolp), 0<pS 1에서의 랜덤표본 X 1, , X,을 관측하는 대신 Y,=min{X,r+1}, i=1,…,n(r은 주어진 자연수) 를 관측할 수 있을 때, Y1, ·, Y",을 이용한 p의 최대가능도 추정량을 구하여라. 6.8 연습문제 (6.3)에서의 Weibull(a,1), a> 0 모형에서 a의 최대가능도 추정 량은 가능도방정식의 근으로 주어지는 것을 밝히고, 이의 일단계 반복법에 의한 풀이를 설명하여라.

## 6.9 4장에서 소개된 일원분류모형

(Ki=Nite-0<NCt8 (e:~N(0,02), i=1,k; j=1,7, 02>0 에서 Al, ., A와 02의 최대가능도 추정량을 구하여라. 6.10 정규분포 N(wo2), -0<<+∞, 0≥ 0 모형에서의 랜덤표본 X 1, ··, Xm 을 이용하여 다음 모수의 최대가능도 추정량을 구하여라. (a) Pro(X,>5a)= 0(0< 0< 1)인 5a (b) 7= Pr,o(X, > a) (Q는 주어진 수) 292 6장 추정

<!-- page 283 -->

## 6.11 연습문제 (6.10)의 (b)에서의 추정량의 극한분포를 구하여라.

6.12 다음 모형에서의 확률밀도함수들이 지수족을 이루는 것을 밝히고 <정리 634>의 조건을 만족시키는지 답하여라. (a) Beta(a,3): a> 0, 3≥ 0 (b) N(0,02), 0<0 <+8

## 6.13 공통의 평균을 갖는 두 정규분포 N(4.01), N(1,03), -8CKK+8,

01>0, 02> 0에서의 랜덤표본을 각각 X1, , Xm과 Y1; , Y,, 이라고 하고 이들 랜덤표본이 서로 독립인 경우에 이들의 결합확률밀도함수가 지수 족을 이루는 것을 밝히고 <정리 6.3.4>의 조건을 만족시키는지 답하여라.

## 6.14 확률밀도함수가

f(a;f,a)= " lp,c)(z) 로 주어지는 두 개의 모수를 갖는 지수분포 EXp(,0), -∞< KC+∞, 0≥0 모형에서의 랜덤표본 X1, ··, X, 을 이용한 다음 모수의 최대가능도 추정량을 구하여라. (a) 0= (/,9)' (b) n=Ppo(X,>ala는 주어진 값)

## 6.15 연습문제 (6.14)의 (b)에서의 추정량의 극한분포를 구하여라.

## 6.16 확률밀도함수가

f(x;0,3)=Bat3-11(a.∞)(2) 로 주어지는 두 개의 모수를 갖는 파레토분포 Pareto(a,3), a> 0, 3≥ 0 모형에서의 랜덤표본 X1, ••, X, 을 이용한 모수 0, 3의 최대가능도 추정량 을 구하여라. 6.17 균등분포 U19,-62:0,+02, -0<9, <+ 0, 02> 0에서의 랜덤표본 Xi, ., X, 을 이용한 모수 01, 02의 최대가능도 추정량을 구하여라.

<!-- page 284 -->

6.18 정규분포 N(4,02) 모형에서 0≤M<+∞, 0”> 0인 경우에 랜덤표본 X 1, ., X, 이용한 모수 A, o2의 최대가능도 추정량을 구하여라.

## 6.19 확률밀도함수가

f(t;a.B)=03 z0-lexp(-29/39)[0+0)(z) 인 와이불분포 Weibull(a.3), 0> 0, 3≥ 0 모형에서의 랜덤표본을 X 1, ·, X, 이라고 할 때 모수 0, 3의 최대가능도 추정량을 구하는 과정을 설명하여 라. (참고: b=1/3°를 이용)

## 6.20 확률밀도함수가

f(2;1,q)= et-8110 o(ltelt-nlay 48.to)(t) 인 로지스틱분포 L(0), -0CM<+0,0≥ 0 모형에서의 랜덤표본을 X1, , X, 이라고 할 때 모수 A,o의 최대가능도 추정량을 구하는 과정을 설명하여라. (참고: 71= 1/0,72=/o를 이용) 6.21 <정리 6.5.3>의 (b)를 증명하여라.

## 6.22 회귀모형

Y;=B,+BitBrite,i=1,.5 〈E(e:)=0, Var(e;)=0,Cor(e;e;)=0(i=j) (3=(3,31,32)'ER,9.>0 에서 직교화를 통하여 다음과 같이 모형을 나타내려고 한다. (B+B,i+B22=N+701t702i=1,0.5 (a) 21; 22i를 구하여라. (b) 70, 71; 72의 최소제곱 주정량을 구하여라. (c) o의 추정량을 제안하여라. 294 6장 추정

<!-- page 285 -->

eriment) 확률변수(1 59 variable) 이산형(해E discrete type) 확률질량함수(HE 319 월 9l probability mass fuction) 확률밀도함수(제 3 12) 엔금만 혼감(대니 or function) 평균(4t mean) probability density function 연속형 기댓값 1값 expected value) 표준편차 (1 continuous type 이상 improper) 확률분포(3¥A) 7 probability distribution) 지표함수(16) (ww cumulative distribution function) 표준지수분포(1부)684th standard exponential distribution) 멱급수(#※및 power series) 확률생 # standard deviation) 표준화(1*ft: standardized) 누적분포함수 1주소htmw probability thbw cumulant generating function) 누율 generating function) 적률생성함수(#구소% moment generating function) 적률(14 moment) 누율생성하 a joint) 주변(B)& marginal) 공분산 (#) 슈R covariance) 상관계수 lant) 이변량(bivariate) 확률벡터(random vector) 반복적분(Iterated integr 합적률생성함수(joint moment gen 결합누율생성함수 joint cumulant generating function) 1병 correlation coefficient) 결합적률(볶습》 joint mor 1t) 조건부(161 conditional) 조건부평균 conditional mean) 조건부기댓값(conditional expected value) 조건부분산 합누율 joint onal variance) 회귀 함수 n vector) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 egression function) 평균제곱예측오차(mean squared prediction error) 행벡F) 2집단분포(B#배Am population distribution) 비복원추출(sampling without replace gative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단 (타 popul 단순랜덤추출(₩※랜덤Itl simple random sampling) 랜덤표본(random sampl ribution) 복원추출(19T.ht sampling with replacement) 이항분 율(Bity population proportion) 초기하분포(1김※(미사) ypergeome ional definition 다항분포(SIA fi multinomial d) Sm binomial distribution) 대의적 정의(fam 2류 repr 분포(#fnAt geometric distribution) 다항계수(※표(%% multinomial coefficie ution) 음이항전개식(negative -TEAT necative binomia 송 과정(Poisson process) al expansion) 포아송(Poiss occurrence rate) 정상성 arity) 독립증분성 (indepe ncrement) 비례성(propo ty) 희귀성(rareness) 지수분 onential distribution) 감마분 검정 ma distribution) 형상모수 arameter) 표준정규분포(1 ape parameter) 척도모수 공간 (1명 d normal distribution) 분위수(upper quanti [본비율(wh Ht w sample proportion) 표본평균(14) 12m parameter space) 통계량(Mat m sta r statistics) 표본중앙값(1A+값 sample medi an) 표본분포(추)7) mean) 표본분산(Aw sample variance) 순서통계량 (NETF M 1g distribution) 위치모수(6Efe location parameter) 척도모수(RIE fi scale 4분포(=Ast triangular distribution) 야코비안 (Jacobian) 자유도 ster) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(49h) (ER deg untform distribut 급분포(chi-squared distribution) 신뢰수준(167k* confidence level) 신뢰구간(165m confidenc irees of freedo 원분류모형 를적분변환 (13 47 ½ 1맛 TA one way classification model) 신뢰집합(fE probability integral transformation) 다변량 정규분포(3m iERRA15 multivariate nor 슴 confidence set) 치환(T19 pe 값(버값 characteristic value) 선형회귀모형(8캔미5천 tion) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(1E 3생교 1ER/th nonsingular multivariate normal dis riable) 계수(61 % rank) 회귀계수(미)% regression regression n 표본회귀계수(sample regression coefficient) 단순 ( (odel) 설명변수(explanatory variable) 반응변수 곱합(자비꽃표제곱합 mean squared erro of squares) 중심극한정리(P0 본초l central imit theorem) 극한분포(6E825) th limitr it simple) c ltion) 점근분포 e) 표본분위수 (배추 yte sample quantile) asymptotic distribution) 대수의 법칙 (가명의 슬럿츠키(Slutsky) 점근 asymptotic) 청예도(460 kurtosis) 표본상관계수(WAN 89g sample of large numbers) 표본적률(sample moment) 분위수(A11평 (r) 몬테칼로적분(Monte Carlo integration) 적률이용추정량(1) 1on coefficient) 분산안정변환(파맛) ormation) 난수(전g random number) 균등난수(E)3월. uniform randl nator) 일치성(- 가능도 함수(피표다 on) 우도(XIE) 최대가능도 추정법 od of moments estimator(MME)) 추정 (11t estimation) 추정량(11 on) 가능도방정식(미#가표 od equation) 순오목함수 concave function) 경계 16R boundary) 다중모수 지수족(3189 9) 181k multi elihood d er exponential family of pdf's) information number) 최소제곱 추정법(least squ 쿨백-라이블러 괴리도 divergence) 점근정규성 (MI IFAR11 al 최소제곱 추정량 (least square 열벡터 공간(column space) 정사영(TE) lity) 점수함수(score functic 조건부확률 1:4] lar projection) 공리(소T axiom) 표본공간(배추 ional probabl ) 사전 prior) 사후(#1 posterior) 독립 확률(적 probab 1lity) 가산가법성 ndependent) 종속(4m mutually depende able addl 확률측도(MixElIs proba 한 실험 (random experiment) 확률변수(7) function) 연속형 able) 이산형 이상( 못: improber) T discrete type) 확률질량함수(제주살 보의 probability mass fuction) 밀도: function) 평균(4k9 mean) 기댓값) 표준편차 standard deviation) 표준화 (4)

## 확률분포(B

Ai probability distribution) 지표함수(11153) distribution function) 표준지수분포 It t stand ibution) 멱급수(#※l power series) 확률생성함수(1%4Nmw probability standardized) 누적분포함수(뽀#Ahmg int) 이변량(bivariate) 확률벡터(random vector) unction) 적률생성함수(#*또hbaw moment generating 반복적분(iterated integral) 결합(A joint) 추변(BR marginal) 공분산(14: covariance) 상관계수(ABS) 0% ction) 적률 moment) 누울생성함수(%84)g cumulant generating function) 누율 (목 누율(joint cumulant) 조건부(18fts conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산 (conditional varian on coefficient) 결합적률(슴#* joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur 열(variance covariance matrix) 정부호(nonnegati (Egapagy regression function) 평균제곱예측오차(mean sauared prediction error) 햄벡터(column vector) 전치(transpose) 평균벡터 (mean vector) 분산 1t population distribution) 비복원추출 기울기벡터(gradient replacement) 단순랜덤추출 (9) ctor) 헤시안행렬(Hessian matrix) 모집단(448 population) 모집단 코비율 (BH,% population proportion) 초기하분포 ic distribution) 복원추출 i simple random sampling) 랜덤표본(random) binomial distribution) 대의적 정의( 다항분포(81E4m multinomis htt sampling with replacement) 이항분포 ficient) 기하분포(Not) th geometh 음이항분포 (| negative binomial distribution) 음이항전개식(negative binomial expar distribution) 다항계수(3I 1B wes multino 송(Poisson) 포아송 과정(Poisson process 'areness) 지수분포(exponel distribution) 감마분포(gamma distribution) 형상모수(HRtg shape parameter) 척도모수(FE E) 및 scale pe 발생률 sTrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성(proportion, 준정규분포(*¥EM;m 주 lte sample proportion) standard nor 표본평균 distribution) 분위수(upper quantile) 모수공간(태호(M parameter space) 통계량(Matm statisti 맛(12pI값 sample med an) 표본분포 ample mean) 표본분산(배추유₩ sample variance) 순서통계량(METWalm order statist ster) 이중지수(double exponential) 코쉬 stribution) 위치모수(11월 he location parameter) 척도모수(FE 함 Jacobian) 자유도(Etlf dearees d 카이제곱분포 균등분포 rm distribution) 삼각분포 ribution) 신뢰수준 (1xl confidence level) 신뢰 - RAmi triangular distributic R confidence interva tion) 확률적분변환 일원분류모형 다변량 정규분포(3: ERAm multivariate norr odel) 신뢰집합 (등##승 confidence set) 치환 ion) 정칙행렬(nons ing 값(피값 characteristic value) 선형회귀모형 x) 정칙 다변량 정규분포 odel) 설명변수(explanator variablp nonsinaular multivanate normal distr 단순(ww simple) 평균오차제곱합(푸19 ionse Variable ) 계수(출1 9g, rank) 회귀계수 1 of squares) 중심극한정리(4) 표본회귀계수(sample regression cr 법칙(*※의 초비 law of large numbers) itral limit theorem) 극한분포(k) 표본적률(sample moment) 분위수(Altg quantile) 표본분으 점근분포(winAt asymptotic distributic A6 sample quantile) 슬럿츠키(Slutsky) 점근(Wfli asymptotic) 첨예도(*sei kurtosis) 표본상
