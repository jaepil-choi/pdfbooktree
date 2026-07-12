# 11.3 베이즈추정량과 최소최대추정량

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 445-457

<!-- page 445 -->

베이즈추정량과 최소최대추정량

자료를 관측하기 전의 정보를 확률로 나타내는 사전분포를 전제로 하는 베이지 안 추론에서는 주어진 자료로부터 갱신된 정보를 나타내는 사후분포가 추론의 근본 이다. 즉 추정량의 선택이나 평가가 모두 주어진 자료로부터의 사후분포에 근거하여 이루어지고, 관측되지 않은 그러나 관측 가능하였던 자료는 추론의 근거로 여기지 않는다. 반면에 사전분포를 전제로 하지 않는 통계적 추론에서는 관측 가능한 모든 자료를 고려하여 특정한 추정량의 반복적 사용에서의 효용성을 평가의 근거로 여기는 것이다. 따라서 이러한 관점에서는 가능한 관측 결과가 반복되는 상대도수를141) 뜻하는 확률분 포 pdf (210)를 기준으로 하는 평균적인 효용성이 평가의 기준이 된다. 예를 들면 실 수 값 모수 0의 추정량 6= 6(x)의 평균제곱오차라고 불리우는 142) 8(a)-0)'pdf (al0)da (연속형 경우) MSE(0,0)= EI(0-0)210]= L(0(x)-0)'pdf (zl0) (이산형 경우) 가 그와 같은 평가 기준 중의 하나이다. 이러한 평균제곱오차를 이용하여 추정량의 비교 기준으로서 베이지안평균제곱오 차143)

## 141) 이와 같이 확률을 반복되는 실험에서의 도수로만 해석하여 통계적 방법의 의미를 찾는

다는 뜻에서 비(#)베이지안(non-Bayesian) 추론의 관점을 빈도적(W9Ef, frequentist's) 관

## 142) 이제까지의 E.(8-0)2]와 같은 표현 대신 베이지안 관점에서는 0가 주어진 조건에서

점이라고도 한다. x의 분포에 대한 기댓값을 뜻하므로 조건부 기댓값을 나타내는 기호로서 E(0-8)701

## 143) 베이지안평균제곱오차 (T,)가 관측 자료 X와 0에 대한 기댓값이라는 것을 강조하

와 같은 표현을 사용하기로 한다. 기 위하여 (7,6)=EX0(0(x)-8)2또는 (T,8)=E(E(8-0)9017 와 같이 나타내기도 한다.

<!-- page 446 -->

(8)= 816-07012(0)20 또는 최대평균제곱오차 max El(0-0)101

## 8E2

가 보편적으로 사용되는 것은 8장에서 소개되었다. 이러한 비교 기준에서 최적의 추 정량을 각각 베이즈추정량, 최소최대추정량이라고 한다. 베이즈추정량과 최소최대추정량: (a) 베이즈추정량: 사전분포 7에 대한 베이지안평균제곱오차를 최소로 하는 추정량 0"를 0의 베이즈추정량이라고 한다. 즉 7(T, 8")= minr(T, 8) (b) 최소최대추정량: 최대평균제곱오차를 최소로 하는 추정량 0"를 0의 최소최대추정 량 또는 미니맥스추정량이라고 한다. 즉 max El("-0)20] =minmaxEl(6-0)201 정리 11.3.1 베이즈추정량 확률밀도함수가 (zl8), 0ED드 R'인 모집단에서의 랜덤표본이 X1, , X., 이고 모수 0의 사전확률밀도함수가 (0) 일 때, 0의 베이즈추정량은 사후평균 제곱오차(posterior mean squared error), 즉 X= (X 1, ,X,,)' = 2가 주어진 조건 에서 평균제곱오차의 기댓값144) El(8(8)-0)31X=2} 을 최소로 하는 사후평균으로 주어진다. 즉 B(z)=agninE(8-6)2x=2}=E(OX =2)

## [증명] 베이지안평균제곱오차는 X와 0의 결합분포에 대한 기댓값으로서

7(T, 8)=B(3.0)((0(x)- 0):1

## 144) 이 정리에서는 이러한 평균제곱오차의 기댓값이 항상 실수로 주어지는 것을 전제로 하

고 있다. 464 11장 베이지안 추론

<!-- page 447 -->

과 같이 나타낼 수 있다. 한편 <정리 2.3.4>에 주어진 조건부기댓값의 성질 로부터 r(T, 8)=E(x.01(0(x)-0)21=EIE((8(X)-0)2x11 임을 알 수 있다. 따라서 B'(c)를 라고 정의하면 8(x)=aremine((@-0x=mh B(8(8)-098=ak2Ef8(X)-8)918=23,V8 (T,@)=EE0(x)-o)%xBEf0(x)-03xh=r(T,o),V8 : min(3.8)=>(3.8), 즉 (3)=0(a)=araminE16-OyX=) 한편 이러한 사후평균제곱오차를 최소로 하는 것이 사후평균임은 명백하다. 즉 arainEl(0-82K=a}=E(OX= 2) <정리 11:3.12은 B=(u,a)'인 경우의 (-w)?/02, (a/o-1) 등과 같이 0가 다차원 모수이고 추정 대상이 모수의 실수값 함수 m= m(0)일 때 추정 오차를 반영하 는 일반적인 손실함수(#샷W, loss function) I(e,m)의 경우에도 성립한다. 이러한 손실함수에 대하여 추정량의 비교 기준으로서 베이지안평균손실을 뜻 하는 함수 을 베이즈위험함수(베이즈{대, Bayes risk function)라고 부르며, 이를 최소로 하는

## 추정량 7"를 손실함수가 I(0,7)인 경우의 베이즈추정량이라고 한다. 즉

1(m.7)= minr(;) 이러한 베이즈추정량은 정리 11.3.1>에서와 같이 사후기대손실(품 1 1) 표를샷, posterior expected 1oss) E{I(0,7)IX= 2)을 최소로 하는 추정량으로 주어진다. 즉 3(z)= argmine{r(0,7)X=2} 베이즈추정량과 마찬가지로 최소최대추정량도 이러한 손실함수의 경우로 일반 화 된다. 즉 최대평균손실을 최소로 하는 추정량 7"을 손실함수가 I(0,7)인 경우 의 최소최대추정량이라고 한다. 즉 max 0E6.7)ol=mjnrexel(0.7) l

<!-- page 448 -->

예 11.3.1 이항 가능도와 베타 사전분포 모형에서 베이즈추정량 베르누이 모집단 Bernoulli(0), 0≤ 0≤ 1에서의 랜덤표본을 X= (X,,,X,,)' 이라고 할 때, 0의 사전분포가 Beta(01, 02), 01> 0, 02> 0이고 손실함수가 제곱오차인 [(0.0)= (6-0)2 인 경우의 베이즈추정량은 <정리 11.3.1>로부터 사후평균 E(OX= 20)로 주어 진다. 따라서 <예 11.1.1>과 <예 11.2.3>으로부터 이 경우의 베이즈추정량은 입=E(비X=2)= n+a1+02 2= 1 예 11.3.2 정규분포 가능도와 켤레 사전분포 모형에서 모평균의 베이즈추정량 정규분포 모집단 N(1,02), -∞<A<+∞, 02> 0에서의 랜덤표본을 X= (X1,,X,,)'이라 하고 0=(,o2)'의 사전분포가 (∞이 주어진 조건에서 N의 조건부분포) 1g:~N(0,82/kio) (02의 역수의 분포) 2003/02 ~ x2(Vo) 이고 손실함수가 I(0.8)=(- 1)2/02 인 경우에 의 베이즈추정량은 사후기대손실 El(0-1)/02X=21 을 최소로 하는 추정량 으로 주어진다. 따라서 베이즈추정량은 B2("-x)03X=2]=0, 즉 =E(wa2X= 2)/E(02X=2) 로 주어진다. 한편 <정리 11.1.2>로부터 0=(A,o2)'의 결합사후분포는 다음과 같이 주어진다. Jr:2 ~N(pn (2), 0:/Rn) (v,0;(2)/02~x(Un) Kin=n+ho: Un=n+v: 52= L(2:-a):/(n-1), Kin (2)=(ntro)-(na thoto), 2,0¾(2)=2008+(n-1)s2+(6al+nl)1(=-Ko)2 466 11장 베이지안 추론

<!-- page 449 -->

따라서 E(WO2X=2)=E[E(Wo 2102,X= 2)X = 21 =Elo-2E(ula) 2,X = 2)|X = 81 =E(o2pn(2)X =2) =12(2)E(a2X= 2) A=E(KoJX=2)/E(o2X=2)=An(t(n+Ro) 1(na tRoto) 예 11.3.3 정규분포 가능도와 켤레 사전분포 모형에서 모분산의 베이즈추정량 <예 11.3.2>에서 손실함수가 다음과 같을 때 2의 베이즈추정량에 대하여 생각해 보자. I(0,02)=(8102-1)2 이 경우에 2의 베이즈추정량은 사후기대손실 El(02/02-1)98=21 을 최소로 하는 추정량 2으로 주어진다. 따라서 베이즈추정량은 E12(0102-1) 0-28= 21= 0, 즉 027 =E(o 2X=2)/E(qHX= 2) 한편 <정리 11.1.2>로부터 o2의 사후분포는 2,0¾(2)1020~x2(0) "2 2,0:(2)=2008+(n-1)82+(60ltn1)(=-10)? "=E(G2X=2)/E(OHX=2)=0,0¾(2)n/(2unten)=

## V,+2

q; (2) 따라서 이 경우의 베이즈추정량은 사후분포의 최빈값과 일치하는 것을 <예 11.2.2>로부터 알 수 있다. 정리 11.3.2 베이즈추정량과 최소최대추정량 모수 OED에 의존하는 모집단에서의 랜덤표본 X=(X1,…,X,,)을 이용한 7=7(0)의 추정량 7/= 77(X)에 대하여 손실함수가 I(0,7)이라고 할 때, 다음

<!-- page 450 -->

두 조건을 만족하는 추정량 7는 최소최대추정량이다. (a) (상주의 위험함수) 45) 평균손실 R (0)=BIL(6,7 )61이 6의 함수로서 상 수 함수이다. 즉 P, (6)=R (6) YBED(38,ED) (b) (베이즈추정량) 77가 베이즈추정량이 되는 사전확률분포 가 존재한다. [증명] 조건 (a)로부터 가 확률분포이므로 한편 조건 (b)로부터 waxf,(0) sminmaxR,(0) 즉 maxP,(6)=minmax R,(8)

## 0E2

예 11.3.4 이항분포 모형에서 최소최대추정량 베르누이 모집단 Bernoulli(0), 0≤ 0≤ 1에서의 랜덤표본 X= (X」, ,X,)' 을 이용하여 0를 추정할 때 제곱오차 손실함수 [(0,0)= (0-0)2 에 대한 최소최대추정량을 구하여라. [풀이] 0의 사전분포가 Beta(a1: 02)인 경우에 예 11.3.1>로부터 베이즈추정량 은 사후평균으로서 다음과 같이 주어지는 것을 알고 있다. gmean = t+a1 드+- a1+a2 7-a1+a2 ntait a2 n ntaita2 alta2 -, t= 231 한편 a6+0(0CaC1,6≥0,8 =특)꼴의 추정량에 대하여 위험함수가 El(a6+6)-0)3101=a0(1-0)/n+(6+(a-1)0)2 로 주어지므로, 상수의 위험함수를 가질 조건은

145) 일반적으로 추정량 7에 대하여 평균손실 P,(0)= EIL (0.7)10]을 0의 함수로서 7의

위험함수(fE W, risk function)라고 한다. 468 11장 베이지안 추론

<!-- page 451 -->

(1-a)’=Q/7, a'/n-26(1-0)=0 .. Q= 1, 0= vm/2 ntvn 따라서 추정량 8'=__" nt vn n 흐+vn/2 nAVn 들은 사전분포가 Beta(vn/2, Vn/2)일 때의 베이즈추정량으로서 상수의 위험함수를 가진다. 그러므로 <정리 11.3.2>로부터 이 추정량이 제곱오차 손실함수에 대한 최소최대추정량 이다.146) 정리 11.3.3 최소호의 사전분포열과 최소최대추정량 모수 0E2에 의존하는 모집단에서의 랜덤표본 X= (X1,,X,)'을 이용한 7=7(8)의 추정량 i=i(X)에 대하여 손실함수가 I(0,7)이라고 할 때, 다음 조건을 만족하는 추정량 7는 최소최대추정량이다. (추정을 가장 어렵게 하는 사전분포147) 열의 존재) 사전확률분포 Tx와 그에 대 한 베이즈추정량 (k= 1,2,··)의 열에 대하여 im x(T5,78) 2 maxP;(6) k-8 [증명] 사전확률분포 x와 그에 대한 베이즈추정량의 정의로부터 따라서 주어진 조건의 부등식으로부터 mintax®;(8) 2limr(77) 2 pexP,(6) maxp, (6)=minmax®,(0)

## 7) 8E2

## 146) 이 최소최대추정량과 최대가능도추정량의 비교를 위하여는 연습문제 (8.1)을 참조하기

바란다.

147) 이러한 사전확률분포의 열 (Tjk=1,2,··}을 최소호의(R)를, least favorable) 사

전분포열이라고 한다.

<!-- page 452 -->

예 11.3.5 정규분포 모형에서 모평균의 최소최대추정량 정규분포 모집단 N(1.o2), -∞<<+∞, 02≥ 0에서의 랜덤표본 X = (X 1,,X,,)'을 이용하여 w를 추정할 때 손실함수 I(0.j)=(x-1)?/02 에 대한 최소최대추정량을 구하여라. [풀이] 0=(w,o2)'의 사전분포가 정리 11.1.2>의 켤레 사전분포인 경우에 베이 즈추정량은 다음과 같이 주어지는 것을 <예 11.3.2>로부터 알고 있다. 8"=1,(z)=(ntro)-(na+RotO) 한편 <정리 11.1.2>에 주어진 0=(/,o2)'의 결합사후분포로부터 No:n~NUn(z),@/Rin), An=ntro : E(w-A):/02102,X=2]=1/(n+ro) 따라서 베이즈추정량의 베이즈위험함수는 7.7)=80801(60):/021=BE(-6)/0202,X)1/(ntro) 그러므로 <정리 11.1.2>의 켤레 사전분포 IMg:~N(W;@/Ro) 1v02102~x2(20) 에서 Ko= 1/k이라고 하고 이 사전분포 열을 (k=1,2,…·)라고 하면 lim r(TK7“)= lim_ 한편 표본평균 A = 3에 대하여 위험함수가 로 주어지므로 다음과 같이 정리 11.3.3>에 주어진 조건이 성립하는 것을 알 수 있다. maxEl(*-A):/020]==≤ lim (7》) 따라서 표본평균 A*=가 주어진 손실함수에 대한 최소최대추정량이다. 470 11장 베이지안 추론

<!-- page 453 -->

일원분류모형 다변량 정규분포 신뢰집합 치환 정칙 다변량 정규분포 화률적분변환 - 계수 회귀계수 고유값 선형회귀모형 정칙행렬 중심극한정리 표본회귀계수 단순 설명변수 점근 대수의 법칙 표본적률 극한분포 점근분포 평균오차지 난수 첨예도 균동난수 표본상관계수 분위수 분산안정변환 표본분위수 •능도 추정법 추정 추정량 몬테칼로 적분 다중모수 지수족 간 점수함수 연습문제 가능도방정식 일치성 가능도 함수 적률이용주정량 쿨백-라이블러 괴리도 순오목함수 확률측도 정사영 조건부확률 공리 최소제곱 추정법 최소제곱 추정량 점근정규성 표본공간 포 할수 확률밀도함수 랜덤한 실험 화률변수 사전 사후 독립 가산가법성 평규 기댓간 연속형 이산형 화률질량함수 표주퍼차 이상 확률분포 표주화

## 11.1 확률밀도함수가

f(a;0)=02-0-11(1,+∞)(2) 로 주어지는 파레토분포 Pareto(1,0), 0> 0에서의 랜덤표본이 Xi,

## X,

이고 0의 사전분포가 Gamma(a,3), a> 0, 3≥ 0일 때, 0의 사후분포를 구 하여라.

## 11.2 다항분포 모형

X=(X1),Xx)~ Multi(n, (p,Px)),p, ++px=1, D,>0, J=1,,k 에서 0=(p1,…p,)'(r=h-1)의 사전분포가 Dirichlet(a1,a,,a,+1) (”=k-1)일 때, 0의 사후분포를 구하여라.

## 11.3 확률밀도함수가

1(a:ko)= dexp-프om) o(), -8CBC+00,020 인 두 개의 모수를 갖는 지수분포 EXp(o)에서의 랜덤표본이 X1, ., 1, 이고, 0=(1,a)'의 사전분포가 다음과 같을 때, 0=(w,o)'의 사후분포를 구하여라. 1(a의 역수의 분포) 0./o~ Gamma(vo,1) (0가 주어진 조건에서 K의 조건부분포) (wo-w)o~Exp(/ro)

## 11.4 선형회귀정규분포 모형

1Y= xgte

## 3E RP+1

e~N,, (0,9:l) , 02> 0, rank(X)=D+1 에서 3와 o2의 사전분포가 다음과 같을 때, 3와 2의 사후분포를 구하여라. (02이 주어진 조건에서 3의 조건부분포) 3~N(Bo,Oko) (o2의 역수의 분포) 200금/02~x2(V0)

<!-- page 454 -->

11.5 지수분포 Exp(0), 0> 0에서의 랜덤표본이 X= (X1,…,Xm)'이고 1=1/0 의 사전분포가 Gamma(a1;02), 01> 0, 02≥ 0일 때, 0의 사후분포로부터 다음을 구하여라. (a) 사후분포의 평균, 중앙값과 최빈값 (b) 신뢰수준 1-a의 0에 관한 베이지안 신뢰구간 11.6 포아송 모집단 Poisson(0), 0≥ 0에서의 랜덤표본이 X= (X 1, ,X,,) 이고 0의 사전분포가 Gamma(a1;a2), o1> 0, 02≥ 0일 때, 0의 사후분포 로부터 다음을 구하여라. (a) 사후분포의 평균, 중앙값과 최빈값 (b) 신뢰수준 1-a의 0에 관한 베이지안 신뢰구간 (c) 표본크기가 큰 경우에 사후분포의 정규근사와 그를 이용한 베이지안 신뢰 구간 11.7 지수분포 Exp(0), 0> 0에서의 랜덤표본 X=(X 1,·X,)'을 이용하여 단 순 가설 10: 0= 00 05 11 : 0= 01 을 검정하는 경우에 사전확률이 T=P(0=0), TI=P(Q=0,)=1-P(0=0.)

## 일 때, 가설 H의 사후승산비를 구하여라.

11.8 지수분포 Exp(0), 0≥ 0에서의 랜덤표본이 X= (X 1, ,X,)'이고 1= 1/0의 사전분포가 Gamma(a,3), a> 0, 3≥ 0인 경우에, 가설 10:0 sPo vs 1:0280 을 검정할 때 가설 140의 사후승산비를 구하여라. 11.9 포아송 모집단 Poisson (0), 0≥ 0에서의 랜덤표본이 X= (X1,…·,X,) 0 고 0의 사전분포가 Gamma(a,B), a> 0, 3> 0인 경우에, 가설 H0:0≤0 vs H:0≥80 472 11장 베이지안 추론

<!-- page 455 -->

을 검정할 때 사후분포의 정규근사를 이용하여 가설 15의 사후승산비를 구 하여라.

## 11.10 확률밀도함수가

J(2;8)= 02-0-211,40) (2) 로 주어지는 파레토분포 Pareto(1,0), 0> 0에서의 랜덤표본이 21, , Am이 고 0의 사전분포가 Gamma(a,B), a> 0, B> 0일 때, 손실함수 I(0,8)=(010-1)2 에 대한 0의 베이즈추정량을 구하여라.

## 11.11 확률밀도함수가

인 두 개의 모수를 갖는 지수분포 Exp(,a)에서의 랜덤표본이 X1, ., X, 이고 0=(/,o)'의 사전분포가 다음과 같다고 하자. 0가 주어진 조건에서 A의 조건부분포) (wo-w)o~Exp(o/kio) 1(o의 역수의 분포) 00/o~Gamma(Vo,1) (a) 손실함수 I(0.p)= (6-)’/o2에 대한 A의 베이즈추정량을 구하여라. (b) 손실함수 I(0,a)=(o/o-1)2에 대한 o의 베이즈추정량을 구하여라. 11.12 베르누이 모집단 Bernoulli(0), 0<8<1에서의 랜덤표본 X=

## (X 1,,X,)'을 이용하여 0를 추정할 때 손실함수가 다음과 같다고 하자.

1(8.8)=16-02 01-8) (a) 0의 사전분포가 균등분포 U(0,1) 일 때 베이즈추정량을 구하여라. (b) 0의 최소최대추정량을 구하여라. 11.13 포아송 모집단 Poisson (8), 8> 0에서의 랜덤표본 X=(X1,,X,,)'을 이용하여 0를 추정할 때 손실함수가 다음과 같다고 하자. [(0,0)=(0-0):/0

<!-- page 456 -->

(a) 0의 사전분포가 Gamma(a,3), a> 0, B> 0일 때 베이즈추정량을 구하 여라. (b) 0의 최소최대추정량을 구하여라. 11.14 지수분포 Exp(0), 0> 0에서의 랜덤표본 X= (X1, ,X,)'을 이용하여 0 를 추정할 때 손실함수가 다음과 같다고 하자. I(0,8)=(610-1)2 (a) A=1/0의 사전분포가 Gamma(a,3), a> 0, 3> 0일 때 0의 베이즈추 정량을 구하여라. (b) 0의 최소최대추정량을 구하여라. 474 11장 베이지안 추론

<!-- page 457 -->

bability density function) 연속형 ment) 확률변수(19%0 random variable) (분포 continuous type) 이상(wt improper) 확률분포(wfi probabilty distribution) 지표함수(1) 9) 이산형(훼룸 discrete type) 확률질량함수(03#제: probability mass fuction) 확률밀도함수(1분 5류 전 7w cumulative distribution function) 표준지수분포(#*16월 4th standard exponential distribution) 멱급수(류&원 power series) 확률생 unction) 평균(TH mean) 기댓값(값 expected value) 표준편차(1¾18분 standard deviation) 표준화(124ft. standardized) 누적분포함수 24imw probability generating function) 적률생성함수(Rittse moment generating function) 적률(# moment) 누율생성하 CBw cumulant generating function) 누율(#* cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integra) 1률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating function) 합누율 joint n oint) 주변(튀: marginal) 공분산(#유품 covariance) 상관계수(ABBN 6%8 correlation coefficient) 결합적률(#슴#% joint mor al variance) 회귀함수(미w regression function) 평균제곱예측오차(mean squared prediction error) 행벡F) 조건부(1% fRi conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산 ector) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 단분포(&#EAfT population distribution) 비복원추출(sampling without replace tive definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(타토 popul) =랜덤추출("※랜덤ItH simple random sampling) 랜덤표본(random sampl ution) 복원추출(15 JMt: sampling with replacement) 이항분 # km population proportion) 초기하분포(분*7) f hypergeome n binomial distribution) 대의적 정의(fteg) 교 repr al definition 다항분포(81Ath multinomial dh 포(whaat geometric distribution) 다항계수(SEK 8 multinomial coefficie (Nt negative binomla expansion) 포아송(Poiss) on) 음이항전개식(negative : 과정(Poisson process) currence rate) 정상성 (ty) 독립증분성 (Indepel 부록 rement) 비례성(propo antial distribution) 감마분 희귀성(rareness) 지수분 a distribution) e parameter) 적도모수(RRd

## ) 형상모수 (HEHX)

ameter) 표준정규분포(#*TER 7 s 간(88쭈m parameter space) 통계량(walm sta ormal distribution) 분위수(upper quanti 비율(WAlt% sample proportion) 표본평균(* TK) rean) 표본분산(#x4w sample variance) 순서통계량(NEFF WEat statistics) 표본중앙값(1☆+맛값 sample medi an) 표본분포(:추)) er) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(H)sf fh uniform distribuu distribution) 위치모수(18w location parameter) 척도모수(RIS Ew scale 분포(=Anm triangular distribution) 야코비안(Jacobian) 자유도(Ettls degrees of freedon, 분포(chisquared distribution) 신뢰수준(6가4 confidence level) 신뢰구간(18ml confidence

## 적분변환 (1 주 F 9 0 1맛

분류모형(-T)평 one way classification model) 신뢰집합(4승 confidence set) 치환(월) per:. on) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(1EE ※ INAt nonsingular multivariate normal dist. probability integral transformation) 다변량 정규분포(3m FRAM multivariate no.. able) 계수(31s rank) 회귀계수(BS%s regression coefficient) 표본회귀계수(sample regression coefficient) 단순(Twt Simple) d (BA값 characteristic value) 선형회귀모형(BS급뽀| linear regression model) 설명변수(explanatory variable) 반응변수.. 곱합(자 1)※제곱합 mean squared error sum of squares) 중심극한정리(TLERNe central limit theorem) 극한분포(NR) th limitire on) 점근분포(Wif th asymptotic distribution) 대수의 법칙(*명의 카 law of large numbers) 표본적률(sample moment) 분위수(911) on coefficient) 분산안정변환(유표고정 표본분위수(배추 9ft sample quantile) variance syabilizing transformation) 난수(88 random number) 균등난수(1799 8l . uniform randon 슬럿츠키(Slutsky) 점근(Wit asymptotic) 첨예도(4sels kurtosis) 표본상관계수(A:NEEN % 18k sample ator) 일치성 (-tt consistency) 가능도 함수(미] E19) 몬테칼로적분(Monte Carlo integration) 적률이용추정량(#제##1분 pw Ikelihood function) 우도(Rg) 최대가능도 추정법(BaN H52: maximum ikelihood e method of moments estimator(MME)) 추정(1lit estimation) 추정량(1f:

7) 가능도방정식(미#it Iikekihood equation) 순오목함수(strictly concave function) 경계(1F boundary) 다중모수 지수족(21 198) 1등회k multi

rexponential family of pdf's) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 점근정규성 (WfiF IE REft asymptotic normality) 점수함수(score functic ##m information number) 최소제곱 추정법(least squares estimation) 최소제곱 추정량(least squares estimator) 열벡터 공간(column space) 정사영(iE) ncicular projection) 공리(21 axiom) 표본공간(8k 2l sample space) 확률(표4 probability) 가산가법성(countable additivity) 확률측도 (161 3 s probe 실험(random experiment) 확률변수(01 후 random variable) 이산형(월 discrete type) 확률질량함수(M주표(2y probability mass fuction) 률밀도 conditional probability) 사전(Tito prior) 사후(#& posterior) 독립(193) mutually independent) 종속(CW mutually depende 9t probability density function) 연속형(토 continuous type) 이상(# improper) 확률분포(35)f probability distribution) 지표함수(119 93) tistribution function) 표준지수분포(1539) th standard exponential distribution) 멱급수(#*Rg power series) 확률생성함수(RF4ftpre probability ge unction) 평균(19 mean) 기댓값(배값 expected value) 표준편차 (14 1 조 standard deviation) 표준화(1*ft standardized) 누적분포함수(월85) 1B) unction) 적률생성함수(#*또#y% moment generating function) 적률(6t moment) 누율생성함수(%※thmg cumulant generating function) 누울 (부 ion coefficient) 결합적률(숨#& joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur ht) 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integral) 결합(A joint) 주변(Bgmarginal) 공분산(#Acovariance) 상관계수(세금품점 66) =(El gpil regression function) 평균제곱예측오차(mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산: =율(joint cumulant) 조건부(18ffw conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variand 1(variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(81 population) 모집단 르비율(tHtt population propor 1ah population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(#※랜덤Htt simple randor sampling) 랜덤표본(random s sinomial distribution) 대의적 정의 tion) 초기하분포(1김(At hypergeometric distribution) 복원추출(1)ittl sampling with replacement) 이항분포 cient) 기하분포(wfA f geometric distribution) 8t wirepresentational definition 다항분포(8184m mutinomial distribution) 다항계수(33 1E6 9 multinor 송(Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성(proportiona 음이항분포(1) IEAT negative binomial distribution) 음이항전개식(negative binomial expan 준정규분포(* IE11h standard normal distribution) 분위수(upper quantile) 모수공간(e 82ml parameter space) 통계량(SENt 로 statistic areness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(HEW shape parameter) 척도모수(RE e B scale pe 값(*☆+ 5값 sample medi Kity sample proportion) 표본평균 (2푸 (an) 표본분포(류추 At sampling distribution) 위치모수(11물함: location parameter) 척도모수(지환 sample mean) 표본분산(Al sample variance) 순서통계량(WEFtStat m order statistr Jacobian) 자유도(Bils degrees of freedom) 카이제곱분포(chisquared distribution) 신뢰수준(1분가:i confidence level) 신뢰.- ster) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(벼)49) f uniform distribution) 삼각분포(=RAt triangular distributic stion) 확률적분변환(Ht 3 7-819 m confidence interval) 일원분류모형 "ml one way classitication m tegral transformation) 다변량 정규분포(3호로 1RGt multivariate norr odel) 신뢰집합 (1등#볶음 confidence set) 치환 값( 값 characteristic value) 선형회귀모형 (5통 ion) 정칙행렬(nons ingular matrix) 정 다변량 정규분포(1L 3 분모 미콤호™ linear regression model) 설명변수(explanatory variable TiAt nonsingular multivariate normal distry 단순(18ft simple) 평균오차제곱합(주)※제곱합 mean squared error sum of squares) 중심극한정리(Pr))) sponse variable) 계수(198 rank) 회귀계수(미) 9h regression coefficient) 표본회귀계수(sample regression cr 법칙(*병의 il law of large numbers) 표본적률(sample moment) 분위수(51 quantile) 표본분이 ntral limit theorem) 극한분포(RAfi limiting distribution) 점근분포(Writitt asymptotic distributior) TVtw sample quantile) 슬럿츠키(Slutsky) 점근(Afiff asymptotic) 첨예도(45 kurtosis) 표본 .., 브 사우진요하
